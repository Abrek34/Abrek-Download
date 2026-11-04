"""Harici araç gerektirmeyen HLS/DASH/konteyner analizi.

Yakalama listesindeki çözünürlük ve ses bilgisini üretmek için ffprobe veya
yt-dlp şart değildir. Bu modül HLS manifestlerini, DASH MPD'lerini, ISO BMFF
(MP4/M4S), MPEG-TS ve WebM/Matroska dosyalarını saf Python ile inceler.
ffprobe/yt-dlp yalnızca tanınmayan veya eksik kalan durumlarda yedek olarak
kullanılır.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from xml.etree import ElementTree


@dataclass(frozen=True)
class MediaProbe:
    """Bir medya örneğinden çıkarılan özellikler."""

    has_video: bool = False
    has_audio: bool = False
    width: int = 0
    height: int = 0
    heights: tuple[int, ...] = ()
    codecs: tuple[str, ...] = ()
    drm: bool = False
    video_known: bool = True
    audio_known: bool = True
    source: str = ""

    @property
    def complete(self) -> bool:
        """Çözünürlük dahil tüm gerekli bilgiler biliniyor mu?"""
        if not self.video_known or not self.audio_known:
            return False
        if self.has_video and self.height <= 0:
            return False
        return True

    def merged(self, other: "MediaProbe | None") -> "MediaProbe":
        """İki analiz sonucunu birleştirir; bilinen alanlar korunur."""
        if other is None:
            return self
        combined_heights = tuple(
            sorted(set(self.heights + other.heights), reverse=True)
        )
        if not combined_heights and max(self.height, other.height) > 0:
            combined_heights = (max(self.height, other.height),)
        return MediaProbe(
            has_video=self.has_video or other.has_video,
            has_audio=self.has_audio or other.has_audio,
            width=max(self.width, other.width),
            height=max(self.height, other.height),
            heights=combined_heights,
            codecs=tuple(dict.fromkeys(self.codecs + other.codecs)),
            drm=self.drm or other.drm,
            video_known=self.video_known or other.video_known,
            audio_known=self.audio_known or other.audio_known,
            source=self.source or other.source,
        )


# --------------------------------------------------------------------- yardımcı
_VIDEO_CODECS = (
    "avc",
    "hvc",
    "hev",
    "vp8",
    "vp9",
    "vp09",
    "av01",
    "mp4v",
    "mpeg2",
    "dvh",
    "dolby",
)
_AUDIO_CODECS = (
    "mp4a",
    "ac-3",
    "ac3",
    "ec-3",
    "eac3",
    "opus",
    "vorbis",
    "flac",
    "alac",
    "mp3",
    "aac",
)
_HLS_ATTR = re.compile(r'([A-Za-z0-9-]+)=("[^"]*"|[^,]*)')


def _parse_attributes(line: str) -> dict[str, str]:
    payload = line.split(":", 1)[1] if ":" in line else ""
    return {
        key.upper(): value.strip().strip('"')
        for key, value in _HLS_ATTR.findall(payload)
    }


def _codec_flags(codecs: str) -> tuple[bool, bool]:
    value = (codecs or "").lower()
    return (
        any(prefix in value for prefix in _VIDEO_CODECS),
        any(prefix in value for prefix in _AUDIO_CODECS),
    )


def _resolution(value: str) -> tuple[int, int]:
    match = re.match(r"(\d+)\s*[xX]\s*(\d+)", value or "")
    if not match:
        return 0, 0
    return int(match.group(1)), int(match.group(2))


# ------------------------------------------------------------------------- HLS
def probe_hls(text: str) -> MediaProbe | None:
    """HLS master/media manifestini inceler."""
    if not text or "#EXTM3U" not in text[:256].upper():
        return None

    streams: list[tuple[int, int, str]] = []
    media_audio = False
    drm = False
    for raw in text.splitlines():
        line = raw.strip()
        upper = line.upper()
        if upper.startswith("#EXT-X-STREAM-INF:"):
            attrs = _parse_attributes(line)
            width, height = _resolution(attrs.get("RESOLUTION", ""))
            streams.append((width, height, attrs.get("CODECS", "")))
        elif upper.startswith("#EXT-X-MEDIA:"):
            attrs = _parse_attributes(line)
            if attrs.get("TYPE", "").upper() == "AUDIO":
                media_audio = True
        elif upper.startswith(("#EXT-X-KEY:", "#EXT-X-SESSION-KEY:")):
            method = _parse_attributes(line).get("METHOD", "").upper()
            # AES-128 normal HLS şifrelemesidir; SAMPLE-AES ise DRM işaretidir.
            if "SAMPLE-AES" in method:
                drm = True

    if not streams:
        # Medya (segment) listesi; çözünürlük bilgisi bir sonraki adımda
        # indirilen segmentten çıkarılır.
        return MediaProbe(
            drm=drm,
            video_known=False,
            audio_known=False,
            source="hls-media",
        )

    has_video = False
    has_audio = media_audio
    width = height = 0
    heights_seen: list[int] = []
    codecs_seen: list[str] = []
    all_codecs = bool(streams)
    all_described = bool(streams)
    for stream_width, stream_height, codecs in streams:
        if stream_width and stream_height:
            has_video = True
            if stream_height > height:
                height = stream_height
                width = stream_width
            elif stream_height == height:
                width = max(width, stream_width)
            heights_seen.append(stream_height)
        if codecs:
            codecs_seen.extend(part.strip() for part in codecs.split(",") if part.strip())
            video_codec, audio_codec = _codec_flags(codecs)
            has_video = has_video or video_codec
            has_audio = has_audio or audio_codec
        else:
            all_codecs = False
        if not (codecs or (stream_width and stream_height)):
            all_described = False

    return MediaProbe(
        has_video=has_video,
        has_audio=has_audio,
        width=width,
        height=height,
        heights=tuple(sorted(set(heights_seen), reverse=True)),
        codecs=tuple(dict.fromkeys(codecs_seen)),
        drm=drm,
        video_known=has_video or all_described,
        audio_known=media_audio or has_audio or all_codecs,
        source="hls",
    )


def hls_first_segment(text: str) -> tuple[str, str]:
    """HLS medya listesinden ``(init_uri, segment_uri)`` döner."""
    init_uri = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.upper().startswith("#EXT-X-MAP:"):
            init_uri = _parse_attributes(line).get("URI", "")
            continue
        if line.startswith("#"):
            continue
        return init_uri, line
    return init_uri, ""


# ------------------------------------------------------------------------ DASH
def _local_name(value: str) -> str:
    return value.rsplit("}", 1)[-1].lower()


def _attributes(element) -> dict[str, str]:
    return {_local_name(key): str(value) for key, value in element.attrib.items()}


def probe_dash(text: str) -> MediaProbe | None:
    """DASH MPD manifestini inceler."""
    if not text or "<MPD" not in text[:4096]:
        return None
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError:
        return None
    if _local_name(root.tag) != "mpd":
        return None

    drm = any(_local_name(element.tag) == "contentprotection" for element in root.iter())
    videos: list[tuple[int, int, str]] = []
    audio_codecs: list[str] = []
    heights_seen: list[int] = []
    all_codecs = True
    found_any = False

    for adaptation in root.iter():
        if _local_name(adaptation.tag) != "adaptationset":
            continue
        base = _attributes(adaptation)
        representations = [
            child for child in adaptation if _local_name(child.tag) == "representation"
        ]
        if not representations:
            representations = [adaptation]
        for representation in representations:
            attrs = {**base, **_attributes(representation)}
            content_type = attrs.get("contenttype", "").lower()
            mime = attrs.get("mimetype", "").lower()
            codecs = attrs.get("codecs", "")
            try:
                height = int(attrs.get("height") or attrs.get("maxheight") or 0)
                width = int(attrs.get("width") or attrs.get("maxwidth") or 0)
            except ValueError:
                height = width = 0
            video_codec, audio_codec = _codec_flags(codecs)
            is_video = (
                content_type == "video"
                or mime.startswith("video/")
                or video_codec
                or height > 0
            )
            is_audio = (
                content_type == "audio"
                or mime.startswith("audio/")
                or (audio_codec and not is_video)
            )
            if not codecs:
                all_codecs = False
            if is_video:
                found_any = True
                videos.append((width, height, codecs))
                if height:
                    heights_seen.append(height)
                if audio_codec:
                    audio_codecs.append(codecs)
            elif is_audio:
                found_any = True
                audio_codecs.append(codecs)

    if not found_any:
        return MediaProbe(drm=drm, video_known=False, audio_known=False, source="dash")

    height = max((item[1] for item in videos), default=0)
    width = max((item[0] for item in videos if item[1] == height), default=0)
    return MediaProbe(
        has_video=bool(videos),
        has_audio=bool(audio_codecs),
        width=width,
        height=height,
        heights=tuple(sorted(set(heights_seen), reverse=True)),
        codecs=tuple(
            dict.fromkeys(
                codec
                for _width, _height, codecs in videos
                for codec in (part.strip() for part in codecs.split(","))
                if codec
            )
        ),
        drm=drm,
        video_known=bool(videos),
        audio_known=bool(audio_codecs) or (bool(videos) and all_codecs),
        source="dash",
    )


# ------------------------------------------------------------------------- MP4
def _boxes(data: bytes, start: int = 0, end: int | None = None):
    limit = len(data) if end is None else min(end, len(data))
    position = start
    while position + 8 <= limit:
        size = struct.unpack_from(">I", data, position)[0]
        box_type = data[position + 4 : position + 8]
        header = 8
        if size == 1:
            if position + 16 > limit:
                break
            size = struct.unpack_from(">Q", data, position + 8)[0]
            header = 16
        elif size == 0:
            size = limit - position
        if size < header or position + size > limit:
            # Kısmi/bozuk kutu; kalan veriyi yorumlamaya çalışma.
            break
        yield box_type, position + header, position + size
        position += size


def _moov_candidates(data: bytes):
    """Dosya başında olmayan (faststart olmayan) moov kutularını bulur."""
    yield 0
    position = 0
    while True:
        index = data.find(b"moov", position)
        if index < 0:
            return
        box_start = index - 4
        if box_start >= 0:
            yield box_start
        position = index + 4


def _tkhd_dimensions(data: bytes, start: int, end: int) -> tuple[int, int]:
    if end <= start:
        return 0, 0
    version = data[start]
    if version == 1:
        width_offset, height_offset = 88, 92
    else:
        width_offset, height_offset = 76, 80
    if end - start < height_offset + 4:
        return 0, 0
    width = struct.unpack_from(">I", data, start + width_offset)[0] >> 16
    height = struct.unpack_from(">I", data, start + height_offset)[0] >> 16
    return int(width), int(height)


def _handler_type(data: bytes, start: int, end: int) -> str:
    if end - start < 12:
        return ""
    return data[start + 8 : start + 12].decode("ascii", errors="ignore")


def probe_mp4(data: bytes) -> MediaProbe | None:
    """ISO BMFF/MP4 dosyasındaki izleri inceler."""
    if len(data) < 16:
        return None

    for candidate in _moov_candidates(data):
        has_video = has_audio = False
        width = height = 0
        drm = False
        found_moov = False
        for box_type, start, end in _boxes(data, candidate):
            if box_type != b"moov":
                continue
            found_moov = True
            drm = b"pssh" in data[start:end]
            for child_type, child_start, child_end in _boxes(data, start, end):
                if child_type != b"trak":
                    continue
                handler = ""
                track_width = track_height = 0
                for track_type, track_start, track_end in _boxes(
                    data, child_start, child_end
                ):
                    if track_type == b"tkhd":
                        track_width, track_height = _tkhd_dimensions(
                            data, track_start, track_end
                        )
                    elif track_type == b"mdia":
                        for media_type, media_start, media_end in _boxes(
                            data, track_start, track_end
                        ):
                            if media_type == b"hdlr":
                                handler = _handler_type(data, media_start, media_end)
                if handler == "vide":
                    has_video = True
                    height = max(height, track_height)
                    width = max(width, track_width)
                elif handler == "soun":
                    has_audio = True
            break
        if found_moov:
            return MediaProbe(
                has_video=has_video,
                has_audio=has_audio,
                width=width,
                height=height,
                heights=(height,) if height else (),
                drm=drm,
                source="mp4",
            )
    return None


# -------------------------------------------------------------------- MPEG-TS
_TS_VIDEO_TYPES = {0x01, 0x02, 0x10, 0x1B, 0x24, 0x42, 0xEA}
_TS_AUDIO_TYPES = {0x03, 0x04, 0x0F, 0x11, 0x1C, 0x81, 0x87}


def _ts_offset(data: bytes) -> int:
    limit = min(188, max(0, len(data) - 2 * 188))
    for start in range(limit):
        if all(
            start + index * 188 < len(data) and data[start + index * 188] == 0x47
            for index in range(3)
        ):
            return start
    return -1


def _section(payload: bytes) -> bytes:
    if not payload:
        return b""
    start = 1 + payload[0]
    if start + 3 > len(payload):
        return b""
    length = ((payload[start + 1] & 0x0F) << 8) | payload[start + 2]
    return payload[start : min(start + 3 + length, len(payload))]


def _pat_pmt_pid(section: bytes) -> int:
    if len(section) < 8 or section[0] != 0x00:
        return 0
    for index in range(8, len(section) - 4, 4):
        program = int.from_bytes(section[index : index + 2], "big")
        pid = ((section[index + 2] & 0x1F) << 8) | section[index + 3]
        if program:
            return pid
    return 0


def _pmt_stream_types(section: bytes) -> list[int]:
    if len(section) < 12 or section[0] != 0x02:
        return []
    program_info = ((section[10] & 0x0F) << 8) | section[11]
    index = 12 + program_info
    types: list[int] = []
    limit = len(section) - 4  # CRC
    while index + 5 <= limit:
        types.append(section[index])
        es_info = ((section[index + 3] & 0x0F) << 8) | section[index + 4]
        index += 5 + es_info
    return types


def _ts_payload(packet: bytes) -> bytes:
    if len(packet) < 5 or packet[0] != 0x47:
        return b""
    if not (packet[1] & 0x40):
        return b""
    adaptation = (packet[3] >> 4) & 0x03
    offset = 4
    if adaptation in (2, 3):
        if len(packet) < 5:
            return b""
        offset = 5 + packet[4]
    if offset >= len(packet):
        return b""
    return packet[offset:]


class _BitReader:
    def __init__(self, data: bytes):
        self.data = data
        self.position = 0

    def read(self, count: int) -> int:
        value = 0
        for _ in range(count):
            byte_index = self.position // 8
            if byte_index >= len(self.data):
                raise ValueError("bit akışı bitti")
            bit = (self.data[byte_index] >> (7 - (self.position % 8))) & 1
            value = (value << 1) | bit
            self.position += 1
        return value

    def skip(self, count: int) -> None:
        self.position += count

    def ue(self) -> int:
        zeros = 0
        while self.read(1) == 0:
            zeros += 1
            if zeros > 31:
                raise ValueError("geçersiz exp-golomb")
        return (1 << zeros) - 1 + (self.read(zeros) if zeros else 0)

    def se(self) -> int:
        value = self.ue()
        return -(value // 2) if value % 2 == 0 else (value + 1) // 2


def _unescape_rbsp(data: bytes) -> bytes:
    result = bytearray()
    zeros = 0
    for byte in data:
        if zeros >= 2 and byte == 0x03:
            zeros = 0
            continue
        result.append(byte)
        zeros = zeros + 1 if byte == 0 else 0
    return bytes(result)


def _skip_scaling_list(reader: _BitReader, size: int) -> None:
    last_scale = 8
    next_scale = 8
    for _ in range(size):
        if next_scale:
            next_scale = (last_scale + reader.se() + 256) % 256
        if next_scale:
            last_scale = next_scale


def _parse_h264_sps(data: bytes) -> tuple[int, int]:
    reader = _BitReader(data)
    profile = reader.read(8)
    reader.skip(8)  # constraint flags + reserved
    reader.read(8)  # level_idc
    reader.ue()  # seq_parameter_set_id
    chroma_format = 1
    if profile in {100, 110, 122, 244, 44, 83, 86, 118, 128, 138, 139, 134, 135}:
        chroma_format = reader.ue()
        if chroma_format == 3:
            reader.read(1)
        reader.ue()  # bit_depth_luma_minus8
        reader.ue()  # bit_depth_chroma_minus8
        reader.read(1)
        if reader.read(1):
            for index in range(8 if chroma_format != 3 else 12):
                if reader.read(1):
                    _skip_scaling_list(reader, 16 if index < 6 else 64)
    reader.ue()  # log2_max_frame_num_minus4
    pic_order = reader.ue()
    if pic_order == 0:
        reader.ue()
    elif pic_order == 1:
        reader.read(1)
        reader.se()
        reader.se()
        for _ in range(reader.ue()):
            reader.se()
    reader.ue()  # max_num_ref_frames
    reader.read(1)  # gaps_in_frame_num_value_allowed_flag
    width_mbs = reader.ue() + 1
    height_units = reader.ue() + 1
    frame_mbs_only = reader.read(1)
    if not frame_mbs_only:
        reader.read(1)
    reader.read(1)  # direct_8x8_inference_flag
    crop_left = crop_right = crop_top = crop_bottom = 0
    if reader.read(1):
        crop_left = reader.ue()
        crop_right = reader.ue()
        crop_top = reader.ue()
        crop_bottom = reader.ue()

    sub_width = 2 if chroma_format in (1, 2) else 1
    sub_height = 2 if chroma_format == 1 else 1
    width = width_mbs * 16 - (crop_left + crop_right) * sub_width
    height = (
        (2 - frame_mbs_only) * height_units * 16
        - (crop_top + crop_bottom) * sub_height * (2 - frame_mbs_only)
    )
    return max(0, width), max(0, height)


def _h264_dimensions(data: bytes) -> tuple[int, int]:
    position = 0
    while position < len(data):
        index = data.find(b"\x00\x00\x01", position)
        if index < 0:
            break
        start = index + 3
        if start >= len(data):
            break
        nal_type = data[start] & 0x1F
        end = data.find(b"\x00\x00\x01", start + 1)
        if end < 0:
            end = min(len(data), start + 4096)
        if nal_type == 7:
            try:
                width, height = _parse_h264_sps(_unescape_rbsp(data[start + 1 : end]))
                if width and height:
                    return width, height
            except (ValueError, IndexError):
                pass
        position = start + 1
    return 0, 0


def probe_mpeg_ts(data: bytes) -> MediaProbe | None:
    """MPEG-TS segmentinden ses/görüntü varlığını çıkarır."""
    offset = _ts_offset(data)
    if offset < 0:
        return None

    pmt_pid = 0
    stream_types: list[int] = []
    for position in range(offset, len(data) - 187, 188):
        packet = data[position : position + 188]
        pid = ((packet[1] & 0x1F) << 8) | packet[2]
        if pid == 0 and not pmt_pid:
            pmt_pid = _pat_pmt_pid(_section(_ts_payload(packet)))
        elif pmt_pid and pid == pmt_pid and not stream_types:
            stream_types = _pmt_stream_types(_section(_ts_payload(packet)))
        if pmt_pid and stream_types:
            break

    if not stream_types:
        return None

    has_video = any(stream_type in _TS_VIDEO_TYPES for stream_type in stream_types)
    has_audio = any(stream_type in _TS_AUDIO_TYPES for stream_type in stream_types)
    if not has_video and not has_audio:
        return None
    width, height = _h264_dimensions(data) if has_video else (0, 0)
    return MediaProbe(
        has_video=has_video,
        has_audio=has_audio,
        width=width,
        height=height,
        heights=(height,) if height else (),
        source="mpegts",
    )


# ----------------------------------------------------------------------- WebM
_EBML_SEGMENT = 0x18538067
_EBML_TRACKS = 0x1654AE6B
_EBML_TRACK_ENTRY = 0xAE
_EBML_TRACK_TYPE = 0x83
_EBML_VIDEO = 0xE0
_EBML_PIXEL_HEIGHT = 0xBA
_EBML_PIXEL_WIDTH = 0xB0
_EBML_CONTENT_ENCODINGS = 0x6D80
_EBML_CONTENT_ENCRYPTION = 0x5035


def _read_vint(data: bytes, position: int, keep_marker: bool) -> tuple[int, int]:
    if position >= len(data):
        raise ValueError("EBML verisi bitti")
    first = data[position]
    mask = 0x80
    length = 1
    while length <= 8 and not (first & mask):
        mask >>= 1
        length += 1
    if length > 8:
        raise ValueError("geçersiz EBML uzunluğu")
    value = first if keep_marker else first & (mask - 1)
    for index in range(1, length):
        if position + index >= len(data):
            raise ValueError("EBML verisi bitti")
        value = (value << 8) | data[position + index]
    return value, position + length


def _ebml_children(data: bytes, start: int, end: int):
    position = start
    while position < end:
        try:
            element_id, after_id = _read_vint(data, position, True)
            size, after_size = _read_vint(data, after_id, False)
        except ValueError:
            return
        child_end = end if size == (1 << (7 * (after_size - after_id))) - 1 else after_size + size
        child_end = min(child_end, end)
        yield element_id, after_size, child_end
        if child_end <= position:
            return
        position = child_end


def _ebml_find(data: bytes, start: int, end: int, target: int):
    for element_id, child_start, child_end in _ebml_children(data, start, end):
        if element_id == target:
            return child_start, child_end
    return None


def _ebml_uint(data: bytes, start: int, end: int) -> int:
    return int.from_bytes(data[start:end], "big") if end > start else 0


def probe_webm(data: bytes) -> MediaProbe | None:
    """WebM/Matroska dosyasındaki TrackEntry'leri inceler."""
    if len(data) < 8 or data[:4] != b"\x1aE\xdf\xa3":
        return None
    try:
        root = _ebml_find(data, 0, len(data), _EBML_SEGMENT)
    except ValueError:
        return None
    if root is None:
        return None
    tracks = _ebml_find(data, root[0], root[1], _EBML_TRACKS)
    if tracks is None:
        return None

    has_video = has_audio = False
    width = height = 0
    drm = False
    track_count = 0
    for element_id, track_start, track_end in _ebml_children(data, tracks[0], tracks[1]):
        if element_id != _EBML_TRACK_ENTRY:
            continue
        track_count += 1
        track_type = 0
        for child_id, child_start, child_end in _ebml_children(
            data, track_start, track_end
        ):
            if child_id == _EBML_TRACK_TYPE:
                track_type = _ebml_uint(data, child_start, child_end)
            elif child_id == _EBML_CONTENT_ENCODINGS:
                if _ebml_find(data, child_start, child_end, _EBML_CONTENT_ENCRYPTION):
                    drm = True
            elif child_id == _EBML_VIDEO:
                track_height = _ebml_find(data, child_start, child_end, _EBML_PIXEL_HEIGHT)
                track_width = _ebml_find(data, child_start, child_end, _EBML_PIXEL_WIDTH)
                if track_height:
                    height = max(height, _ebml_uint(data, *track_height))
                if track_width:
                    width = max(width, _ebml_uint(data, *track_width))
        if track_type == 1:
            has_video = True
        elif track_type == 2:
            has_audio = True

    if not track_count:
        return None
    return MediaProbe(
        has_video=has_video,
        has_audio=has_audio,
        width=width,
        height=height,
        heights=(height,) if height else (),
        drm=drm,
        source="webm",
    )


# ----------------------------------------------------------------------- giriş
def probe_bytes(data: bytes, text: str = "", url: str = "") -> MediaProbe | None:
    """Bayt/veri türüne göre uygun yerleşik ayrıştırıcıyı dener."""
    if not data and not text:
        return None

    manifest_text = text or ""
    if not manifest_text and data[:512].lstrip().startswith(b"#EXTM3U"):
        manifest_text = data.decode("utf-8", errors="replace")
    if manifest_text and "#EXTM3U" in manifest_text[:256].upper():
        result = probe_hls(manifest_text)
        if result is not None:
            return result

    mpd_text = text or ""
    if not mpd_text and b"<MPD" in data[:4096]:
        mpd_text = data.decode("utf-8", errors="replace")
    if mpd_text and "<MPD" in mpd_text[:4096]:
        result = probe_dash(mpd_text)
        if result is not None:
            return result

    if data.startswith(b"\x1aE\xdf\xa3"):
        result = probe_webm(data)
        if result is not None:
            return result
    if _ts_offset(data) >= 0:
        result = probe_mpeg_ts(data)
        if result is not None:
            return result
    if b"ftyp" in data[:64] or b"moov" in data or b"moof" in data:
        result = probe_mp4(data)
        if result is not None:
            return result
    return None
