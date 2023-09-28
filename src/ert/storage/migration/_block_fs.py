from __future__ import annotations
import enum
import zlib
from dataclasses import dataclass
from functools import partial
from pathlib import Path
import struct
from typing import (
    TYPE_CHECKING,
    Any,
    Generator,
    Iterable,
    List,
    Mapping,
    MutableSequence,
    Optional,
    Sequence,
    Set,
    Tuple,
)
from mmap import mmap, MAP_PRIVATE, PROT_READ

import numpy as np

if TYPE_CHECKING:
    import numpy.typing as npt


class Kind(enum.IntEnum):
    FIELD = 104
    GEN_KW = 107
    SUMMARY = 110
    GEN_DATA = 113
    SURFACE = 114
    EXT_PARAM = 116


@dataclass
class Block:
    kind: Kind
    name: str
    report_step: int
    realization_index: int
    length: int
    offset: int
    count: int


class DataFile:
    def __init__(self, path: Path) -> None:
        self._blocks: Mapping[Kind, List[Block]] = {
            kind: [] for kind in Kind.__members__.values()
        }
        self._realizations: Set[int] = set()

        self._file = path.open("rb")

        try:
            self._mmap = mmap(self._file.fileno(), 0, flags=MAP_PRIVATE, prot=PROT_READ)
        except ValueError:
            # "cannot mmap an empty file"
            return

        offset = 0
        while (offset := self._mmap.find(b"\x55\x55\x55\x55", offset)) >= 0:
            offset += 4
            self._read_block_index(offset)

    def close(self) -> None:
        self._mmap.close()
        self._file.close()

    def blocks(self, kind: Kind) -> Iterable[Block]:
        return self._blocks[kind]

    def load_field(self, block: Block, count_hint: int) -> npt.NDArray[np.float32]:
        return self._load_vector_compressed(block, count_hint, np.float32)

    def load(
        self, block: Block, count_hint: Optional[int] = None
    ) -> npt.NDArray[np.float64]:
        count: int = 0
        if block.kind in (Kind.GEN_KW, Kind.SURFACE, Kind.EXT_PARAM):
            if count_hint is not None and count_hint != block.count:
                raise ValueError(
                    f"On-disk vector has {block.count} elements, but ERT config expects {count_hint}"
                )
            count = block.count
        elif block.kind in (Kind.SUMMARY, Kind.GEN_DATA):
            count = block.count
        else:
            raise TypeError("Unknown block kind")

        if block.kind == Kind.GEN_DATA:
            return self._load_vector_compressed(block, count, np.float64)
        else:
            return self._load_vector(block, count)

    @property
    def realizations(self) -> Set[int]:
        return self._realizations

    def _load_vector_compressed(
        self, block: Block, count_hint: int, dtype: Union[np.float32, np.float64]
    ) -> npt.NDArray[Any]:
        compdata = self._mmap[block.offset : block.offset + block.length]
        uncompdata = zlib.decompress(compdata)
        return np.frombuffer(uncompdata, dtype=dtype, count=count_hint)

    def _load_vector(self, block: Block, count: int) -> npt.NDArray[np.float64]:
        return np.frombuffer(
            self._mmap[block.offset : block.offset + block.length],
            dtype=np.float64,
            count=count,
        )

    def _read_block_index(self, offset: int) -> None:
        name, offset = self._read_str(offset)

        # Skip node_size
        offset += 4

        data_size, offset = self._read_u32(offset)

        # Skip something else
        data_size -= 8
        offset += 8
        count: int = 0

        kind = Kind.from_bytes(self._mmap[offset : offset + 4], "little")
        data_size -= 4
        offset += 4
        if kind == Kind.SUMMARY:
            count, offset = self._read_u32(offset)

            # Skip default value (float64)
            offset += 8
            data_size -= 8
        elif kind == Kind.GEN_DATA:
            count, offset = self._read_u32(offset)

            # Skip report_step (uint32)
            offset += 8

        elif kind in (Kind.SURFACE, Kind.GEN_KW):
            # The count is given in the config and not available in the
            # data file, but we can make an informed guess by looking
            # at the size of the whole data section
            count = data_size // 8  # sizeof(double) == 8
        elif kind == Kind.FIELD:
            # The count is given in the config
            pass
        elif kind == Kind.EXT_PARAM:
            raise RuntimeError("Migrating EXT_PARAM is not supported")

        name_, report_step, realization_index = parse_name(name, kind)
        self._blocks[kind].append(
            Block(
                kind=kind,
                name=name_,
                report_step=report_step,
                realization_index=realization_index,
                offset=offset,
                length=data_size,
                count=count,
            )
        )

    def _read_str(self, offset: int) -> Tuple[str, int]:
        length, offset = self._read_u32(offset)
        string = self._mmap[offset : offset + length].decode("ascii")
        return string, offset + length + 1  # `+ 1`: Skip NULL

    def _read_u32(self, offset: int) -> Tuple[int, int]:
        value = struct.unpack_from("I", self._mmap, offset)[0]
        return (value, offset + 4)


def parse_name(name: str, kind: Kind) -> Tuple[str, int, int]:
    if (index := name.rfind(".")) < 0:
        raise ValueError(f"Key '{name}' has no realization index")
    if kind == Kind.SUMMARY:
        return (name[:index], 0, int(name[index + 1 :]))

    if (index_ := name.rfind(".", 0, index - 1)) < 0:
        raise ValueError(f"Key '{name}' has no report step")
    return (name[:index_], int(name[index_ + 1 : index]), int(name[index + 1 :]))
