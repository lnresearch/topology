import sys
import time
from .common import DatasetFile
import click
import networkx as nx
from .parser import ChannelAnnouncement, ChannelUpdate, NodeAnnouncement
from tqdm import tqdm
from datetime import datetime


@click.group()
def timemachine():
    pass


@timemachine.command()
@click.argument("dataset", type=DatasetFile())
@click.argument("timestamp", type=int, required=False)
@click.option('--fmt', type=click.Choice(['dot', 'gml', 'graphml'], case_sensitive=False))
def restore(dataset, timestamp=None, fmt='dot'):
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

    nodes = [n for n in nodes.values() if n["in_degree"] > 0 or n['out_degree'] > 0]

    if len(channels) == 0:
        print(
            "ERROR: no channels are left after pruning, make sure to select a"
            "timestamp that is covered by the dataset."
        )
        sys.exit(1)

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
        for line in nx.generate_graphml(g):
            print(line)
