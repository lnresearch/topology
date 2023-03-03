import sys
import time
from .common import DatasetFile
import click
import networkx as nx
from .parser import ChannelAnnouncement, ChannelUpdate, NodeAnnouncement
from tqdm import tqdm
from datetime import datetime
import json
from networkx.readwrite import json_graph
import requests
import os
import csv 

@click.group()
def timemachine():
    pass


@timemachine.command()
@click.argument("dataset", type=DatasetFile())
@click.argument("timestamp", type=int, required=False)
@click.option('--fmt', type=click.Choice(['dot', 'gml', 'graphml', 'json'], case_sensitive=False))
@click.option('--fix_missing', type=click.Choice(['recover','filter'], case_sensitive=False))
def restore(dataset, timestamp=None, fmt='dot', fix_missing=None):
    """Restore reconstructs the network topology at a specific time in the past.

    Restore replays gossip messages from a dataset and reconstructs
    the network as it would have looked like at the specified
    timestamp in the past. The network is then printed to stdout using
    the format specified with `--fmt`.

    """
    if timestamp is None:
        timestamp =    time.time()

    cutoff = timestamp - 2 * 7 * 24 * 3600
    channels = {}
    nodes = {}
    cache_file = "./data/channels_cache.csv"

    # Some target formats do not suport UTF-8 aliases.
    codec = 'UTF-8' if fmt in ['dot'] else 'ASCII'

    for m in tqdm(dataset, desc="Replaying gossip messages"):
        if isinstance(m, ChannelAnnouncement):

            channels[f"{m.short_channel_id}/0"] = {
                "source": m.node_ids[0].hex(),
                "destination": m.node_ids[1].hex(),
                "timestamp": 0,
                "features": m.features.hex(),
            }

            channels[f"{m.short_channel_id}/1"] = {
                "source": m.node_ids[1].hex(),
                "destination": m.node_ids[0].hex(),
                "timestamp": 0,
                "features": m.features.hex(),
            }

        elif isinstance(m, ChannelUpdate):
            scid = f"{m.short_channel_id}/{m.direction}"
            chan = channels.get(scid, None)
            ts = m.timestamp

            if ts > timestamp:
                # Skip this update, it's in the future.
                continue

            if ts < cutoff:
                # Skip updates that cannot possibly keep this channel alive
                continue

            if chan is None:
                raise ValueError(
                    f"Could not find channel with short_channel_id {scid}"
                )

            if chan["timestamp"] > ts:
                # Skip this update, it's outdated.
                continue

            chan["timestamp"] = ts
            chan["fee_base_msat"] = m.fee_base_msat
            chan["fee_proportional_millionths"] = m.fee_proportional_millionths
            chan["htlc_minimim_msat"] = m.htlc_minimum_msat
            if m.htlc_maximum_msat:
                chan["htlc_maximum_msat"] = m.htlc_maximum_msat
            chan["cltv_expiry_delta"] = m.cltv_expiry_delta
        elif isinstance(m, NodeAnnouncement):
            node_id = m.node_id.hex()

            old = nodes.get(node_id, None)
            if old is not None and old["timestamp"] > m.timestamp:
                continue

            alias = m.alias.replace(b'\x00', b'').decode(codec, 'ignore')
            nodes[node_id] = {
                "id": node_id,
                "timestamp": m.timestamp,
                "features": m.features.hex(),
                "rgb_color": m.rgb_color.hex(),
                "alias": alias,
                "addresses": ",".join([str(a) for a in m.addresses]),
                "out_degree": 0,
                "in_degree": 0,
            }

    # Cleanup pass: drop channels that haven't seen an update in 2 weeks
    todelete = []
    for scid, chan in tqdm(channels.items(), desc="Pruning outdated channels"):
        if chan["timestamp"] < cutoff:
            todelete.append(scid)
        else:
            node = nodes.get(chan["source"], None)
            if node is None:
                continue
            else:
                node["out_degree"] += 1
            node = nodes.get(chan["destination"], None)
            if node is None:
                continue
            else:
                node["in_degree"] += 1

    for scid in todelete:
        del channels[scid]

    if len(channels) == 0:
        print(
            "ERROR: no channels are left after pruning, make sure to select a"
            "timestamp that is covered by the dataset."
        )
        sys.exit(1)

    if fix_missing is not None:
        # If fix_missing is set, find channels that don't have edge data for both directions
        unmatched = []
        removed = []
        for scid, chan in tqdm(channels.items(), desc="Finding unmatched channels"):
           
            if scid[-2:] == "/0":
                opposite_scid = scid[:-2] + "/1"
            elif scid[-2:] == "/1":
                opposite_scid = scid[:-2] + "/0"
            else:
                raise Exception("ERROR: unknown scid format.")
           
            if opposite_scid not in channels:
                unmatched.append(scid)

        if fix_missing == "recover":
            # Attempt to recover missing edges
            if os.path.exists(cache_file) and os.stat(cache_file).st_size > 0:
                with open(cache_file, 'r') as f:
                    reader = csv.reader(f)
                    channels_cache = {rows[0]:json.loads(rows[1]) for rows in reader}
            else:
                channels_cache = dict()

            for scid in tqdm(unmatched, desc="Attempting to recover missing edges"):
                undirected_scid = scid[:-2]
                if undirected_scid in channels_cache:
                    # If possible, retrieve edge data from the cache file
                    recovered_chan = channels_cache[undirected_scid]
                else:
                    # Else, request edge data from a LN explorer and save it in the cache file
                    scid_elements = [ int(i) for i in undirected_scid.split("x") ]
                    converted_scid = scid_elements[0] << 40 | scid_elements[1] << 16 | scid_elements[2]
                    url = "https://1ml.com/channel/" + str(converted_scid) + "/json"
                    resp = requests.get(url)

                    if resp.status_code == 200:
                        recovered_chan = resp.json()
                    else:
                        raise Exception("ERROR: unable to retrieve channel.")
                    
                    os.makedirs(os.path.dirname(cache_file), exist_ok=True)
                    with open(cache_file, 'w+') as f:
                        writer = csv.writer(f)
                        writer.writerow([undirected_scid, json.dumps(recovered_chan)])

                direction = int(not bool(int(scid[-1:])))

                if direction == 0:
                    recovered_data = recovered_chan["node1_policy"]
                else:
                    recovered_data = recovered_chan["node2_policy"]
                
                chan = channels.get(scid, None)

                if not all(recovered_data.values()):
                    # If no useful data could be found, remove the channel
                    node = nodes.get(chan["source"], None)
                    if node is None:
                        continue
                    node["out_degree"] -= 1
                    node = nodes.get(chan["destination"], None)
                    if node is None:
                        continue
                    node["in_degree"] -= 1
                    removed.append(channels[scid])
                    del channels[scid]
                
                else:
                    # Add recovered edge to the graph
                    channels[scid[:-1] + str(direction)] = {
                        "source": chan["destination"],
                        "destination": chan["source"],
                        "timestamp": chan["timestamp"],
                        "features": chan["features"],
                        "fee_base_msat": recovered_data["fee_base_msat"],
                        "fee_proportional_millionths": recovered_data["fee_rate_milli_msat"],
                        "htlc_minimum_msat": recovered_data["min_htlc"],
                        "cltv_expiry_delta": recovered_data["time_lock_delta"] }

                    node = nodes.get(chan["destination"], None)
                    if node is None:
                        continue
                    node["out_degree"] += 1
                    node = nodes.get(chan["source"], None)
                    if node is None:
                        continue
                    node["in_degree"] += 1

        if fix_missing == "filter":
            # Remove channels that don"t have edge data for both directions
            for scid in tqdm(unmatched, desc="Removing unmatched edges from the graph"):
                chan = channels.get(scid, None)
                node = nodes.get(chan["source"], None)
                if node is None:
                    continue
                node["out_degree"] -= 1
                node = nodes.get(chan["destination"], None)
                if node is None:
                    continue
                node["in_degree"] -= 1
                removed.append(channels[scid])
                del channels[scid]


        print('WARNING:', len(removed), "channels were removed from the graph due to missing edges")


    nodes = [n for n in nodes.values() if n["in_degree"] > 0 or n["out_degree"] > 0]

    # Export graph
    g = nx.DiGraph()
    for n in nodes:
        g.add_node(n["id"], **n)

    for scid, c in channels.items():
        g.add_edge(c["source"], c["destination"], scid=scid, **c)

    if fmt == 'dot':
        print(nx.nx_pydot.to_pydot(g))

    elif fmt == 'gml':
        for line in nx.generate_gml(g):
            print(line)

    elif fmt == 'graphml':
        for line in nx.generate_graphml(g, named_key_ids=True, edge_id_from_attribute='scid'):
            print(line)

    elif fmt == 'json':
        print(json.dumps(json_graph.adjacency_data(g)))
