import click
import bz2
from pyln.proto.primitives import varint_decode
from lntopo.parser import parse
from pathlib import Path
import struct


class DatasetStream:
    def __init__(self, file_stream, decode=True):
        self.stream = file_stream
        self.decode = decode

        # Read header
        header = self.stream.read(4)
        assert len(header) == 4
        assert header[:3] == b"GSP"
        assert header[3] == 1

    def __iter__(self):
        return self

    def __next__(self):
        
        try:
        
            pos = self.stream.tell()
            length = varint_decode(self.stream)

            if length is None:
                raise StopIteration()

            msg = self.stream.read(length)
            if len(msg) != length:
                raise ValueError(
                    "Error reading dataset at {pos}: incomplete read of {length} bytes, only got {mlen} bytes".format(
                        pos=pos, length=length, mlen=len(msg)
                    )
                )
            if not self.decode:
                return msg

            return parser.parse(msg)

        except Exception as ex:
            
            return ''


class DatasetFile(click.File):
    def __init__(self, decode=True):
        click.File.__init__(self)
        self.decode = decode

    def convert(self, value, param, ctx):
        f = bz2.open(value, "rb") if value.endswith(".bz2") else open(value, "rb")
        return DatasetStream(f, self.decode)

class GossipStore:
    """A gossip_store file allowing streaming of messages.
    """

    def __init__(self, path: Path):
        self.path = path

    def __iter__(self):
        with open(self.path, 'rb') as f:
            self.version, = struct.unpack("!B", f.read(1))
            while True:
                hdr = f.read(8)
                if len(hdr) < 8:
                    break

                length, crc = struct.unpack("!II", hdr)
                if self.version > 3:
                    f.read(4)  # Throw away the CRC

                # deleted = (length & 0x80000000 != 0)
                # important = (length & 0x40000000 != 0)
                length = length & (~0x80000000) & (~0x40000000)
                msg = f.read(length)
                typ, = struct.unpack("!H", msg[:2])
                if self.version <= 3 and typ in [4096, 4097, 4098]:
                    msg = msg[4:]

                yield msg
