import json
import click
from lntopo.timemachine import timemachine
from lntopo.common import GossipStore
from lntopo import common
from binascii import unhexlify
from lntopo import parser


@click.group()
def cli():
    pass


cli.add_command(timemachine)

@cli.group()
def nodes():
    pass

@nodes.command(name='trace')
@click.argument('node_id')
@click.argument('gossip_store', type=click.Path(exists=True))
@click.option('-p', '--parse')
def nodes_trace(node_id: str, gossip_store, parse):
    """Given a gossip store, only emit messages relating to a node
    """
    gs = GossipStore(gossip_store)

    chanids = []
    node_id = unhexlify(node_id)

    for m in gs:
        if m[0] != 0x01 or m[1] not in [0x00, 0x01, 0x02]:
            continue
        m = parser.parse(m)

        if isinstance(m, parser.ChannelAnnouncement) and node_id in m.node_ids:
            chanids.append(m.short_channel_id)
            print(json.dumps(m.__json__()))

        elif isinstance(m, parser.ChannelUpdate) and  m.short_channel_id in chanids:
            print(json.dumps(m.__json__()))

        elif isinstance(m, parser.NodeAnnouncement) and m.node_id == node_id:
            print(json.dumps(m.__json__()))


@cli.group()
def messages():
    pass

@messages.command(name='parse')
@click.argument('msg')
def messages_parse(msg):
    msg = unhexlify(msg)
    print(msg[:10])
    if msg[0] == 0x01 and msg[1] in [0x00, 0x01, 0x02]:
        print(json.dumps(common.parse(msg).__json__()))

if __name__ == "__main__":
    cli()
