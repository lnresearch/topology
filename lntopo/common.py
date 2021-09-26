import click
import bz2
from pyln.proto.primitives import varint_decode
from .parser import parse


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

        return parse(msg)


class DatasetFile(click.File):
    def __init__(self, decode=True):
        click.File.__init__(self)
        self.decode = decode

    def convert(self, value, param, ctx):
        f = bz2.open(value, "rb") if value.endswith(".bz2") else open(value, "rb")
        return DatasetStream(f, self.decode)
