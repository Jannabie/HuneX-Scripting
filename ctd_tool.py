#!/usr/bin/env python3
"""
CTD Script Tool - LenZuCompressor (HuneX Engine)
Game  : Witch on the Holy Night (Mahoyo) Remastered - TYPE-MOON
Format: LenZu = LZ77 back-references + Huffman coding (MSB-first)

Developed for: Oby
---------------------------------------------------------------
CTD File Structure:
  0x00  16 bytes  Magic: "LenZuCompressor\\0"
  0x10   4 bytes  Version: 0x31 ('1')
  0x14   4 bytes  Header size: 0x30 (48 bytes)
  0x18   8 bytes  Padding (zeroes)
  0x20   4 bytes  Decompressed size (uint32 LE)
  0x24   4 bytes  CRC-64 high word
  0x28   4 bytes  CRC-64 low word
  0x2C   4 bytes  (unused field)
  0x30   6 bytes  Codec params [_,huffBcRaw,huffBcMin,brLowBcXUpper,brLowBc,brBaseDist]
  0x36   1 byte   entries_to_fill (0 = first_real_entry = 128)
  0x37  512 bytes Huffman frequency table (128 x uint32 LE)
  0x237  ...       LZ77+Huffman bitstream (MSB-first)

LZ77 Token format (MSB-first bits):
  [1 bit: 0=literal | 1=backref]
  [Huffman symbol: length]
  if literal:  emit (length_sym+1) raw bytes, each 8 bits
  if backref:  eff_len  = length_sym + brBaseDist (2)
               [Huffman symbol: dist_high]
               [7 raw bits: dist_low]
               distance = (dist_high<<7) | dist_low + brBaseDist
               copy eff_len bytes from (write_pos - distance)

Huffman tree notes:
  - Standard min-heap construction (lowest weight merged first)
  - Stable tie-break via insertion counter
  - invert=True: bit 0 -> RIGHT child, bit 1 -> LEFT child

Usage:
  python3 ctd_tool.py  info         <file.ctd>
  python3 ctd_tool.py  decompress   <file.ctd>   [output.txt]
  python3 ctd_tool.py  compress     <input.txt>  [output.ctd]
"""

import struct, heapq, sys
from math import ceil
from pathlib import Path

# -------------------------------------------------------
MAGIC_FULL = (b'LenZuCompressor\x00'
              b'\x31\x00\x00\x00'
              b'\x30\x00\x00\x00'
              b'\x00\x00\x00\x00\x00\x00\x00\x00')

BANNER = (
    "\n"
    "+==========================================================+\n"
    "|          CTD Script Tool  -  LenZuCompressor             |\n"
    "|      Witch on the Holy Night Remastered (TYPE-MOON)      |\n"
    "+==========================================================+\n"
)

# Codec parameters (matching all original CTD files)
HUFF_BC_RAW     = 7
HUFF_BC_MIN     = 7
BR_LOW_BC_UPPER = 14
BR_LOW_BC       = 7
BR_BASE_DIST    = 2
FRE             = 1 << HUFF_BC_RAW   # 128
MAX_SYM         = FRE - 1            # 127
MAX_LIT_LEN     = MAX_SYM + 1        # 128 bytes per literal token
MAX_MATCH_LEN   = MAX_SYM + BR_BASE_DIST  # 129 bytes per copy
MIN_MATCH_LEN   = BR_BASE_DIST       # 2
MIN_DISTANCE    = BR_BASE_DIST       # 2
MAX_DISTANCE    = ((MAX_SYM << BR_LOW_BC) | MAX_SYM) + BR_BASE_DIST  # 16385

# -------------------------------------------------------
# CRC
# -------------------------------------------------------
def _lenzu_crc(data: bytes) -> int:
    lut = [0x0e9, 0x115, 0x137, 0x1b1]
    crc = 0
    for i, b in enumerate(data):
        crc = ((crc + b) * lut[i & 3]) % (1 << 64)
    return crc

# -------------------------------------------------------
# Huffman
# -------------------------------------------------------
def _build_tree(weights):
    """Build Huffman tree with stable counter tiebreaker.
    Node: [weight, counter, symbol, left, right]
    invert=True means: bit 0 -> right, bit 1 -> left during traversal.
    """
    counter = [0]
    def make(s, w):
        c = counter[0]; counter[0] += 1
        return [w, c, s, None, None]
    heap = [make(s, w) for s, w in weights if w > 0]
    heapq.heapify(heap)
    while len(heap) > 1:
        a = heapq.heappop(heap); b = heapq.heappop(heap)
        c = counter[0]; counter[0] += 1
        heapq.heappush(heap, [a[0]+b[0], c, None, a, b])
    return heap[0] if heap else None

def _decode_sym(root, br):
    """Decode one symbol: bit=0 -> right, bit=1 -> left (invert=True)."""
    n = root
    while n[3] is not None or n[4] is not None:
        n = n[4] if br.bit() == 0 else n[3]
    return n[2]

def _build_code_table(root):
    """Return {symbol: bitstring}. bit '0' = right, bit '1' = left."""
    codes = {}
    def walk(node, code):
        if node[3] is None and node[4] is None:
            codes[node[2]] = code if code else '0'
            return
        if node[4] is not None: walk(node[4], code + '0')
        if node[3] is not None: walk(node[3], code + '1')
    walk(root, '')
    return codes

# -------------------------------------------------------
# Bit I/O
# -------------------------------------------------------
class BitReader:
    def __init__(self, data, start, end):
        self.data = data; self.pos = start; self.end = end
        self.buf = 0; self.cnt = 0; self.exhausted = False
    def bit(self):
        if self.cnt == 0:
            if self.pos >= self.end: self.exhausted = True; return 0
            self.buf = self.data[self.pos]; self.pos += 1; self.cnt = 8
        self.cnt -= 1
        return (self.buf >> self.cnt) & 1
    def bits(self, n):
        v = 0
        for _ in range(n): v = (v << 1) | self.bit()
        return v

class BitWriter:
    def __init__(self):
        self.buf = 0; self.cnt = 0; self.out = bytearray()
    def write_bit(self, b):
        self.buf = (self.buf << 1) | (b & 1); self.cnt += 1
        if self.cnt == 8:
            self.out.append(self.buf); self.buf = 0; self.cnt = 0
    def write_bits(self, val, n):
        for i in range(n-1, -1, -1): self.write_bit((val >> i) & 1)
    def write_code(self, codestr):
        for ch in codestr: self.write_bit(int(ch))
    def getbytes(self):
        if self.cnt > 0:
            self.out.append(self.buf << (8 - self.cnt))
        return bytes(self.out)

# -------------------------------------------------------
# LZ77 Parser
# -------------------------------------------------------
def _lz77_parse(data: bytes):
    """Greedy LZ77 parse. Yields ('lit', bytes) or ('ref', length, distance)."""
    n = len(data); pos = 0; lit_buf = bytearray(); ht = {}

    def _hash3(p):
        if p + 3 > n: return None
        return (data[p] ^ (data[p+1] << 4) ^ (data[p+2] << 8)) & 0xFFFF

    def _find_match(p):
        if p + MIN_MATCH_LEN > n: return 0, 0
        h = _hash3(p)
        if h is None: return 0, 0
        bl = MIN_MATCH_LEN - 1; bd = 0
        for cp in reversed(ht.get(h, [])[-16:]):
            d = p - cp
            if d < MIN_DISTANCE or d > MAX_DISTANCE: continue
            ml = 0
            while p+ml < n and ml < MAX_MATCH_LEN and data[cp+ml] == data[p+ml]:
                ml += 1
            if ml > bl: bl = ml; bd = d
            if bl == MAX_MATCH_LEN: break
        return bl, bd

    def _add_hash(p):
        h = _hash3(p)
        if h is None: return
        if h not in ht: ht[h] = []
        ht[h].append(p)

    def _flush_lit():
        nonlocal lit_buf
        while lit_buf:
            chunk = bytes(lit_buf[:MAX_LIT_LEN])
            lit_buf = lit_buf[MAX_LIT_LEN:]
            yield ('lit', chunk)

    while pos < n:
        ml, md = _find_match(pos)
        if ml >= MIN_MATCH_LEN:
            yield from _flush_lit()
            yield ('ref', ml, md)
            for i in range(ml): _add_hash(pos + i)
            pos += ml
        else:
            lit_buf.append(data[pos]); _add_hash(pos); pos += 1
            if len(lit_buf) == MAX_LIT_LEN:
                yield from _flush_lit()

    yield from _flush_lit()

# -------------------------------------------------------
# Decompress
# -------------------------------------------------------
def lenzu_decompress(data: bytes) -> bytes:
    if data[:16] != b'LenZuCompressor\x00':
        raise ValueError("Not a LenZu CTD file (bad magic)")

    pos = 0x30
    _, huffBcRaw, huffBcMin, brLowBcXUpper, brLowBc, brBaseDist = data[pos:pos+6]
    pos += 6
    huffBitCount = max(huffBcRaw, huffBcMin)
    fre = 1 << huffBitCount
    ib  = ceil(huffBitCount / 8)
    iby = ceil(ib / 8)

    etf = int.from_bytes(data[pos:pos+iby], 'little'); pos += iby
    if etf == 0: etf = fre
    dense = fre * 4 < (ib + 4) * etf

    if dense:
        raw_w = list(struct.unpack_from(f'<{etf}I', data, pos)); pos += etf * 4
        weights = list(enumerate(raw_w))
    else:
        weights = []
        for _ in range(etf):
            idx = int.from_bytes(data[pos:pos+iby], 'little'); pos += iby
            wt  = int.from_bytes(data[pos:pos+4],   'little'); pos += 4
            weights.append((idx, wt))

    decomp_len = struct.unpack_from('<I', data, 0x20)[0]
    root = _build_tree(weights)
    br   = BitReader(data, pos, len(data))

    output = bytearray(decomp_len); wp = 0
    while wp < decomp_len and not br.exhausted:
        is_backref = br.bit() != 0
        length = _decode_sym(root, br)
        if length is None: break
        if is_backref:
            length += brBaseDist
            dist_high = _decode_sym(root, br)
            if dist_high is None: break
            dist_low = br.bits(brLowBc) if brLowBc > 0 else 0
            distance = (dist_high << brLowBc) | dist_low
            distance += brBaseDist
            rp = wp - distance
            for i in range(length):
                if wp >= decomp_len: break
                output[wp] = output[rp + i]; wp += 1
        else:
            for _ in range(length + 1):
                if wp >= decomp_len: break
                output[wp] = br.bits(8); wp += 1

    return bytes(output)

# -------------------------------------------------------
# Compress
# -------------------------------------------------------
def lenzu_compress(plaintext: bytes) -> bytes:
    hR=HUFF_BC_RAW; hM=HUFF_BC_MIN; blXU=BR_LOW_BC_UPPER; blBC=BR_LOW_BC; bD=BR_BASE_DIST
    fre=FRE; ib=ceil(max(hR,hM)/8); iby=ceil(ib/8)

    # Pass 1: tokenise
    tokens = list(_lz77_parse(plaintext))

    # Count frequencies (seed=1 so all symbols appear in table)
    freq = [1] * fre
    for t in tokens:
        if t[0] == 'lit':
            freq[len(t[1]) - 1] += 1
        else:
            _, ml, md = t
            freq[ml - bD] += 1
            freq[(md - bD) >> blBC] += 1

    # Build Huffman
    weights = list(enumerate(freq))
    root    = _build_tree(weights)
    codes   = _build_code_table(root)

    # Pass 2: encode bitstream
    bw = BitWriter()
    for t in tokens:
        if t[0] == 'lit':
            bw.write_bit(0)
            bw.write_code(codes[len(t[1]) - 1])
            for b in t[1]: bw.write_bits(b, 8)
        else:
            _, ml, md = t
            de = md - bD
            dh = de >> blBC
            dl = de & ((1 << blBC) - 1)
            bw.write_bit(1)
            bw.write_code(codes[ml - bD])
            bw.write_code(codes[dh])
            if blBC > 0: bw.write_bits(dl, blBC)

    stream = bw.getbytes()

    # Huffman frequency table (dense)
    huff_tbl = (fre).to_bytes(iby, 'little')
    for i in range(fre):
        huff_tbl += struct.pack('<I', freq[i])

    # Header
    decomp_len = len(plaintext)
    crc  = _lenzu_crc(plaintext)
    crcH = (crc >> 32) & 0xFFFFFFFF
    crcL = crc & 0xFFFFFFFF
    opts = bytes([0, hR, hM, blXU, blBC, bD])

    header = (MAGIC_FULL
              + struct.pack('<I', decomp_len)
              + struct.pack('<I', crcH)
              + struct.pack('<I', crcL)
              + struct.pack('<I', 0)
              + opts)

    return header + huff_tbl + stream

# -------------------------------------------------------
# CLI Commands
# -------------------------------------------------------
def cmd_info(ctd_path):
    print(BANNER)
    path = Path(ctd_path)
    if not path.exists(): print(f"[ERROR] File not found: {ctd_path}"); sys.exit(1)
    data = path.read_bytes()
    if data[:16] != b'LenZuCompressor\x00':
        print(f"[ERROR] Not a valid CTD file"); sys.exit(1)

    pos = 0x30
    _, hR, hM, blXU, blBC, bD = data[pos:pos+6]
    hBC = max(hR, hM); fre = 1<<hBC; ib = ceil(hBC/8); iby = ceil(ib/8)
    etf = int.from_bytes(data[pos+6:pos+6+iby], 'little')
    if etf == 0: etf = fre
    dm  = fre*4 < (ib+4)*etf
    table_size  = iby + (etf*4 if dm else (ib+4)*etf)
    stream_start = 0x36 + table_size
    decomp_len = struct.unpack_from('<I', data, 0x20)[0]
    crcH = struct.unpack_from('<I', data, 0x24)[0]
    crcL = struct.unpack_from('<I', data, 0x28)[0]

    print(f"  File         : {path.name}")
    print(f"  Size         : {len(data):,} bytes ({len(data)/1024:.1f} KB)")
    print(f"  Decomp size  : {decomp_len:,} bytes ({decomp_len/1024:.1f} KB)")
    print(f"  Ratio        : {decomp_len/len(data):.2f}x")
    print(f"  CRC-64       : 0x{(crcH<<32)|crcL:016x}")
    print(f"  huffBitCount : {hBC} (raw={hR} min={hM})")
    print(f"  brLowBc      : {blBC} (xUpper={blXU})")
    print(f"  brBaseDist   : {bD}")
    print(f"  Table mode   : {'dense' if dm else 'indexed'} ({etf} entries)")
    print(f"  Stream start : 0x{stream_start:x}")
    print(f"  Stream size  : {len(data)-stream_start:,} bytes")


def cmd_decompress(ctd_path, out_path=None):
    print(BANNER)
    path = Path(ctd_path)
    if not path.exists(): print(f"[ERROR] File not found: {ctd_path}"); sys.exit(1)
    data = path.read_bytes()
    print(f"  Input  : {path.name}  ({len(data):,} bytes)")

    out = lenzu_decompress(data)

    if out_path is None:
        out_path = str(path.parent / (path.stem + '.txt'))
    Path(out_path).write_bytes(out)
    print(f"  Output : {out_path}  ({len(out):,} bytes)")
    print()
    try:
        sample = out[:200].decode('utf-8', errors='strict')
        print("  Preview:")
        for ln in sample.replace('\r\n','\n').splitlines()[:4]:
            print(f"    {ln}")
    except Exception:
        print(f"  (first bytes: {out[:20].hex()})")
    print()
    print("  Done!")


def cmd_compress(txt_path, out_path=None):
    print(BANNER)
    path = Path(txt_path)
    if not path.exists(): print(f"[ERROR] File not found: {txt_path}"); sys.exit(1)
    plaintext = path.read_bytes()
    print(f"  Input  : {path.name}  ({len(plaintext):,} bytes)")
    print(f"  Compressing (LZ77 + Huffman)...")

    compressed = lenzu_compress(plaintext)

    if out_path is None:
        out_path = str(path.with_suffix('.ctd'))
    Path(out_path).write_bytes(compressed)
    ratio = len(plaintext) / len(compressed)
    print(f"  Output : {out_path}  ({len(compressed):,} bytes)")
    print(f"  Ratio  : {ratio:.2f}x  ({len(plaintext):,} -> {len(compressed):,})")
    print()
    print("  Done!")


def usage():
    print(BANNER)
    print("  Commands:")
    print("    python3 ctd_tool.py  info         <file.ctd>")
    print("    python3 ctd_tool.py  decompress   <file.ctd>   [output.txt]")
    print("    python3 ctd_tool.py  compress     <input.txt>  [output.ctd]")
    print()
    print("  Examples:")
    print("    python3 ctd_tool.py  info         script_text_en.ctd")
    print("    python3 ctd_tool.py  decompress   script_text_en.ctd")
    print("    python3 ctd_tool.py  decompress   script_text_en.ctd  en_script.txt")
    print("    python3 ctd_tool.py  compress     en_script.txt       script_text_en.ctd")
    print()


def main():
    if len(sys.argv) < 3: usage(); sys.exit(0)
    cmd = sys.argv[1].lower()
    if cmd == 'info':
        cmd_info(sys.argv[2])
    elif cmd in ('decompress', 'extract', 'decode'):
        cmd_decompress(sys.argv[2], sys.argv[3] if len(sys.argv) >= 4 else None)
    elif cmd in ('compress', 'pack', 'encode'):
        cmd_compress(sys.argv[2], sys.argv[3] if len(sys.argv) >= 4 else None)
    else:
        print(f"[ERROR] Unknown command: '{sys.argv[1]}'"); usage(); sys.exit(1)

if __name__ == '__main__':
    main()
