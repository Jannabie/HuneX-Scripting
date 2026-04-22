#!/usr/bin/env python3
"""
CTD Script Tool v2 - LenZuCompressor (HuneX Engine)
Game  : Witch on the Holy Night (Mahoyo) Remastered - TYPE-MOON
Format: LenZu = LZ77 back-references + Huffman coding (MSB-first)

Developed for: Oby / Moonlit Translation
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
  0x37  ...       Huffman freq table + LZ77+Huffman bitstream (MSB-first)

LZ77 Token format (MSB-first bits):
  [1 bit: 0=literal | 1=backref]
  [Huffman symbol: length]
  if literal:  emit (length_sym+1) raw bytes, each 8 bits
  if backref:  eff_len  = length_sym + brBaseDist (2)
               [Huffman symbol: dist_high]
               [7 raw bits: dist_low]
               distance = (dist_high<<7) | dist_low + brBaseDist
               copy eff_len bytes from (write_pos - distance)

=== HuneX Script Tag Reference (Mahoyo Steam) ===

  <text|ruby>           Ruby / furigana display.
                        • In JA: <漢字|ふりがな>  (4 679 uses)
                        • In EN/ZC/ZT: <Latin|Translation>  (bilingual chant)
                        ⚠ PRESERVE EXACTLY — engine renders ruby from this.

  <text|@p-N/ruby>      Ruby with horizontal-offset positioning.
                        N is a signed pixel offset for alignment.
                        Example: <仇|@p-1/かたき>
                        ⚠ PRESERVE @p tag and value.

  <text|@_hidden>       Bilingual chant where the ruby text starts with @_
                        The @_ prefix marks "hidden original language" shown
                        smaller beneath the main text.
                        Example: <招き入れる|@_Venite domum meam.>
                        ⚠ PRESERVE @_ prefix.

  ^                     Soft line-break inside a single text block.
                        Text continues without a player click.
                        Example: "It was a day^ like any other in December."
                        ⚠ PRESERVE — removing changes text flow.

  @o                    ★ ITALIC / outside-voice font trigger.
                        Placed at the very start of a line (no space before it).
                        Seen on 1 EN line, 7 JA lines, ~10 ZC/ZT lines.
                        The engine renders this line using an italic/decorative
                        font (outside-voice mode).
                        ⚠ PRESERVE at line start.
                        ⚠ Do NOT replace @o with leading spaces — they are NOT
                          equivalent. Missing @o = wrong font in-game.

  (text)                ★ ITALIC internal monologue — EN SCRIPT ONLY.
                        Parentheses signal the engine to switch to the italic
                        font (FONT_en_italic_00).  There is NO extra binary tag
                        — the ( ) characters themselves trigger italic rendering.
                        Does NOT appear in JA/ZC/ZT scripts (those use different
                        conventions for internal thoughts).
                        ⚠ KEEP ( ) when translating thoughts! (EN only)

  [onpu]                ♪ Music-note glyph.
                        The engine substitutes [onpu] with a ♪ symbol from the
                        game's custom font.  Used in sung lyrics / chants.
                        Example:  唱着六便士之歌～[onpu]
                        ⚠ PRESERVE exactly as [onpu] — removing it breaks layout.

  [swel] [eywz]         Rune-glyph tags — font-embedded rune symbols.
  [ansz] [ingz]         The engine substitutes each tag with the corresponding
                        Elder Futhark rune glyph from the custom font:
                          [ansz] → ᚨ Ansuz     [swel] → ᛊ Sowilo
                          [eywz] → ᛇ Eiwaz     [ingz] → ᛜ Ingwaz
                        Always wrapped in a ruby tag to give the reading:
                          <[swel]|ソウェル>
                        ⚠ PRESERVE the glyph name AND its surrounding ruby.

  ITALIC (manual)       ✗ You CANNOT add italic manually to arbitrary text.
                        The only italic triggers are:
                          1. @o at line start  (outside-voice mode)
                          2. (text) parentheses  (EN script internal thoughts)
                        There is no inline italic tag like <i> or [i].

  BOLD                  ✗ There is NO bold tag in this engine — at all.
                        Confirmed absent in JA, ZC, ZT, and EN scripts.
                        The HuneX format does not support inline bold markup.
                        Emphasis is done via ruby annotations, font choice
                        (@o italic, thought italic), or glyph symbols.

  Indentation           Leading spaces encode the visual/audio channel:
                        0 sp = top-level narration or chant
                        2 sp = standard character dialogue / narration
                        4+ sp = nested/choral/background text layers
                        ⚠ PRESERVE leading spaces.

Usage:
  python3 ctd_tool.py  info         <file.ctd>
  python3 ctd_tool.py  decompress   <file.ctd>   [output.txt]
  python3 ctd_tool.py  compress     <input.txt>  [output.ctd]
  python3 ctd_tool.py  tags         <file.txt>
  python3 ctd_tool.py  validate     <original.txt>  <edited.txt>
"""

import struct, heapq, sys, re
from math import ceil
from pathlib import Path
from collections import Counter

# -------------------------------------------------------
MAGIC_FULL = (b'LenZuCompressor\x00'
              b'\x31\x00\x00\x00'
              b'\x30\x00\x00\x00'
              b'\x00\x00\x00\x00\x00\x00\x00\x00')

BANNER = (
    "\n"
    "+==========================================================+\n"
    "|        CTD Script Tool v2  -  LenZuCompressor            |\n"
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

# Known glyph names -> human-readable description
KNOWN_GLYPHS = {
    'onpu': '♪  music note',
    'swel': 'ᛊ  Sowilo rune',
    'eywz': 'ᛇ  Eiwaz rune',
    'ansz': 'ᚨ  Ansuz rune',
    'ingz': 'ᛜ  Ingwaz rune',
}

# -------------------------------------------------------
# Tag extraction helpers
# -------------------------------------------------------
RE_RUBY    = re.compile(r'<([^|>\r\n]+)\|([^>\r\n]+)>')
RE_AT_P    = re.compile(r'@p(-?\d+)/')
RE_AT_O    = re.compile(r'^@o', re.MULTILINE)
RE_CARET   = re.compile(r'\^')
RE_THOUGHT = re.compile(r'^\s*\(', re.MULTILINE)
RE_AT_UND  = re.compile(r'@_')
RE_GLYPH   = re.compile(r'\[([a-z]+)\]')


def _collect_tags(text: str) -> dict:
    """Return a dict of tag stats for the given text."""
    lines = text.split('\r\n')
    rubies   = RE_RUBY.findall(text)
    at_p     = RE_AT_P.findall(text)
    at_o     = [l for l in lines if l.startswith('@o')]
    at_und   = RE_AT_UND.findall(text)
    carets   = RE_CARET.findall(text)
    thoughts = [l for l in lines if l.strip().startswith('(')]
    glyphs   = RE_GLYPH.findall(text)
    return {
        'ruby':     rubies,
        'at_p':     at_p,
        'at_o':     at_o,
        'at_und':   at_und,
        'caret':    carets,
        'thoughts': thoughts,
        'glyphs':   glyphs,
        'lines':    lines,
    }


def _print_tag_summary(stats: dict, label: str = ""):
    r, p, o, u, c, t, g = (
        stats['ruby'], stats['at_p'], stats['at_o'],
        stats['at_und'], stats['caret'], stats['thoughts'],
        stats['glyphs']
    )
    prefix = f"  [{label}] " if label else "  "
    print(f"{prefix}Lines    : {len(stats['lines']):,}")
    print(f"{prefix}Ruby     : {len(r):,}  (<text|ruby>)")
    print(f"{prefix}@p pos   : {len(p):,}  (@p-N/ inside ruby)")
    print(f"{prefix}@o italic: {len(o):,}  (@o line-start → italic/outside-voice font)")
    print(f"{prefix}@_ hidden: {len(u):,}  (@_ inside ruby)")
    print(f"{prefix}^ breaks : {len(c):,}  (soft line-breaks)")
    print(f"{prefix}(thought): {len(t):,}  (italic monologue — EN script only)")
    print(f"{prefix}[glyph]  : {len(g):,}  ([onpu] ♪ / rune glyphs)")


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
    n = root
    while n[3] is not None or n[4] is not None:
        n = n[4] if br.bit() == 0 else n[3]
    return n[2]

def _build_code_table(root):
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

    tokens = list(_lz77_parse(plaintext))

    freq = [1] * fre
    for t in tokens:
        if t[0] == 'lit':
            freq[len(t[1]) - 1] += 1
        else:
            _, ml, md = t
            freq[ml - bD] += 1
            freq[(md - bD) >> blBC] += 1

    weights = list(enumerate(freq))
    root    = _build_tree(weights)
    codes   = _build_code_table(root)

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

    huff_tbl = (fre).to_bytes(iby, 'little')
    for i in range(fre):
        huff_tbl += struct.pack('<I', freq[i])

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
        text = out.decode('utf-8')
        stats = _collect_tags(text)

        lines = stats['lines']
        print("  Preview (first 4 non-empty lines):")
        shown = 0
        for ln in lines:
            if ln.strip():
                print(f"    {ln[:100]}")
                shown += 1
                if shown >= 4: break
        print()

        print("  ── Tag Summary ──────────────────────────────────")
        _print_tag_summary(stats)
        print()
        print("  Tag legend:")
        print("    <text|ruby>      = ruby/furigana or bilingual chant")
        print("    <text|@pN/..>    = ruby with pixel-offset positioning")
        print("    <text|@_..>      = chant with hidden original-language marker")
        print("    ^                = soft line-break (no click needed)")
        print("    @o               = ★ ITALIC outside-voice font (line start only!)")
        print("    (...)            = ★ ITALIC internal thought  (EN script only)")
        print("    [onpu]           = ♪ music-note glyph")
        print("    [swel/eywz/ansz/ingz] = rune-symbol glyphs (inside ruby)")
        print("    spaces           = indentation = dialogue depth/channel")
        print("    BOLD             = ✗ not supported — no bold tag in this engine")
        print()
        print("  ⚠ All tags above are PRESERVED during compress.")
        print("    @o MUST stay at line start — do NOT swap for spaces!")
        print("    Keep ( ) for italic thoughts in EN scripts!")
        print("    Keep [onpu]/rune glyphs and their surrounding ruby!")
    except UnicodeDecodeError:
        print(f"  (first bytes: {out[:20].hex()})")

    print()
    print("  Done!")


def cmd_compress(txt_path, out_path=None):
    print(BANNER)
    path = Path(txt_path)
    if not path.exists(): print(f"[ERROR] File not found: {txt_path}"); sys.exit(1)
    plaintext = path.read_bytes()
    print(f"  Input  : {path.name}  ({len(plaintext):,} bytes)")

    try:
        text = plaintext.decode('utf-8')
        stats = _collect_tags(text)
        print()
        print("  ── Input Tag Summary ────────────────────────────")
        _print_tag_summary(stats)
        print()
    except UnicodeDecodeError:
        print("  [WARNING] File is not valid UTF-8 — skipping tag check")

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


def cmd_tags(txt_path):
    """Detailed tag report for a decompressed .txt file."""
    print(BANNER)
    path = Path(txt_path)
    if not path.exists(): print(f"[ERROR] File not found: {txt_path}"); sys.exit(1)

    try:
        text = path.read_bytes().decode('utf-8')
    except UnicodeDecodeError:
        print("[ERROR] File is not valid UTF-8"); sys.exit(1)

    stats = _collect_tags(text)
    print(f"  File : {path.name}")
    print()

    # ── Overall summary ──
    print("  ── Tag Count Summary ────────────────────────────────")
    _print_tag_summary(stats)
    print()

    # ── Italic / font mode info (always shown) ──
    print("  ── Italic & Bold Reference ──────────────────────────")
    print("    @o  (line start)   → ★ italic / outside-voice font in-game")
    print("                          ⚠ must stay at column 0, NOT replaced by spaces")
    print("    (thought)          → ★ italic internal monologue (EN script only)")
    print("                          ⚠ keep ( ) when translating EN thoughts")
    print("    BOLD               → ✗ NOT supported — no bold tag exists in this engine")
    print("    Inline italic      → ✗ NOT supported — no <i> or [i] tag; only @o/(..)")
    print()

    # ── Ruby detail ──
    rubies = stats['ruby']
    if rubies:
        print(f"  ── Ruby tags  ({len(rubies)} total) ─────────────────────")
        at_p_rubies  = [(m, r) for m, r in rubies if r.startswith('@p')]
        at_u_rubies  = [(m, r) for m, r in rubies if r.startswith('@_')]
        plain_rubies = [(m, r) for m, r in rubies
                        if not r.startswith('@p') and not r.startswith('@_')]
        print(f"    Plain <text|reading>       : {len(plain_rubies)}")
        print(f"    With @p offset <t|@p-N/r>  : {len(at_p_rubies)}")
        print(f"    With @_ hidden <t|@_orig>  : {len(at_u_rubies)}")
        print()
        print("    Sample plain rubies:")
        for m, r in plain_rubies[:5]:
            print(f"      <{m[:25]}|{r[:25]}>")
        if at_p_rubies:
            print("    Sample @p rubies:")
            for m, r in at_p_rubies[:3]:
                print(f"      <{m[:25]}|{r[:35]}>")
        if at_u_rubies:
            print("    Sample @_ rubies:")
            for m, r in at_u_rubies[:3]:
                print(f"      <{m[:25]}|{r[:35]}>")
        print()

    # ── @o italic lines ──
    at_o = stats['at_o']
    if at_o:
        print(f"  ── @o italic/outside-voice lines  ({len(at_o)} total) ───")
        print("    ★ Rendered in italic / decorative font by the engine.")
        print("    ⚠ @o must be at column 0 — missing or replaced @o = wrong font!")
        for l in at_o[:5]:
            print(f"    {repr(l[:100])}")
        print()
    else:
        print(f"  ── @o italic/outside-voice lines  (0 total) ────────")
        print("    None found.  If this is an EN/ZC/ZT script, check for")
        print("    lines that should start with @o but have leading spaces instead.")
        print()

    # ── (thought) italic monologue ──
    thoughts = stats['thoughts']
    if thoughts:
        print(f"  ── (thought) italic lines  ({len(thoughts)} total) ──────")
        print("    ★ Rendered in italic font (FONT_en_italic_00).  EN script only.")
        print("    ⚠ Keep ( ) delimiters when translating!")
        print()
        for l in thoughts[:5]:
            print(f"    {repr(l.strip()[:100])}")
        print()
    else:
        print(f"  ── (thought) italic lines  (0 total) ───────────────")
        print("    None found.  (thought) italic only appears in EN scripts.")
        print()

    # ── Glyph tags ──
    glyphs = stats['glyphs']
    if glyphs:
        glyph_counter = Counter(glyphs)
        print(f"  ── [glyph] font-symbol tags  ({len(glyphs)} total) ────────")
        for name, count in glyph_counter.most_common():
            desc = KNOWN_GLYPHS.get(name, '(unknown — add to KNOWN_GLYPHS)')
            print(f"    [{name:6}] : {count:3}  →  {desc}")
        print()
        glyph_lines = [(i+1, l) for i, l in enumerate(stats['lines'])
                       if RE_GLYPH.search(l)]
        print(f"    Lines containing glyphs ({len(glyph_lines)}):")
        for n, l in glyph_lines[:6]:
            print(f"      [{n:5}] {l[:100]}")
        unknown = [n for n in glyph_counter if n not in KNOWN_GLYPHS]
        if unknown:
            print()
            print(f"    ⚠ Unknown glyph names: {unknown}")
            print(f"       Add them to KNOWN_GLYPHS in ctd_tool.py if you identify them.")
        print()
    else:
        print(f"  ── [glyph] font-symbol tags  (0 total) ─────────────")
        print("    No [onpu]/rune glyphs found.")
        print()

    # ── Caret breaks ──
    carets = stats['caret']
    if carets:
        lines = stats['lines']
        caret_lines = [(i, l) for i, l in enumerate(lines) if '^' in l]
        print(f"  ── ^ soft line-breaks  ({len(carets)} total in {len(caret_lines)} lines) ──")
        for i, l in caret_lines[:5]:
            print(f"    [{i+1:5}] {repr(l[:100])}")
        print()

    # ── Indentation analysis ──
    lines = stats['lines']
    indent_counts = Counter()
    for l in lines:
        if l.strip():
            n = len(l) - len(l.lstrip(' '))
            indent_counts[n] += 1
    print("  ── Indentation levels (leading spaces) ──────────────")
    for n_sp, count in sorted(indent_counts.items()):
        bar = '█' * min(count // 50, 40)
        role = {
            0: "top-level / chant / @o lines",
            2: "standard narration / dialogue",
            4: "nested / secondary",
            6: "tertiary layer",
            8: "deep / choral",
        }.get(n_sp, "...")
        print(f"    {n_sp:2d} spaces : {count:5,}  {bar}  ({role})")
    print()

    # ── Malformed tag check ──
    malformed = re.findall(r'<[^>\r\n]{0,80}(?:\r\n|$)', text)
    unclosed  = [m for m in malformed if '|' not in m and len(m) > 1]
    if unclosed:
        print(f"  ⚠ Possibly unclosed/malformed <...> ({len(unclosed)}):")
        for m in unclosed[:5]:
            print(f"    {repr(m[:80])}")
    else:
        print("  ✓ No malformed <...> tags found.")
    print()


def cmd_validate(orig_path, edited_path):
    """Compare tag counts between original and edited .txt — warn on mismatches."""
    print(BANNER)
    orig_p  = Path(orig_path)
    edit_p  = Path(edited_path)
    for p in (orig_p, edit_p):
        if not p.exists(): print(f"[ERROR] File not found: {p}"); sys.exit(1)

    try:
        orig_text = orig_p.read_bytes().decode('utf-8')
        edit_text = edit_p.read_bytes().decode('utf-8')
    except UnicodeDecodeError as e:
        print(f"[ERROR] {e}"); sys.exit(1)

    orig_stats = _collect_tags(orig_text)
    edit_stats = _collect_tags(edit_text)

    print(f"  Original : {orig_p.name}")
    print(f"  Edited   : {edit_p.name}")
    print()

    checks = [
        ('Ruby <text|ruby>',          'ruby',    lambda s: len(s['ruby'])),
        ('@p offset ruby',             'at_p',   lambda s: len(s['at_p'])),
        ('@o italic/outside-voice',    'at_o',   lambda s: len(s['at_o'])),
        ('@_ hidden ruby',             'at_und', lambda s: len(s['at_und'])),
        ('^ soft-break',               'caret',  lambda s: len(s['caret'])),
        ('(thought) italic [EN only]', 'thought',lambda s: len(s['thoughts'])),
        ('[glyph] font symbols',       'glyphs', lambda s: len(s['glyphs'])),
    ]

    all_ok = True
    print("  ── Validation Results ───────────────────────────────")
    for label, key, fn in checks:
        ov = fn(orig_stats)
        ev = fn(edit_stats)
        if ov == ev:
            status = "✓ OK   "
            detail = f"{ov}"
        else:
            status = "✗ DIFF "
            detail = f"orig={ov}  edited={ev}  ({ev-ov:+d})"
            all_ok = False
        print(f"    {status}  {label:<32} {detail}")

    # Line count
    ol = len(orig_stats['lines'])
    el = len(edit_stats['lines'])
    if ol == el:
        print(f"    ✓ OK     {'Line count':<32} {ol}")
    else:
        print(f"    ! NOTE   {'Line count':<32} orig={ol}  edited={el}  ({el-ol:+d})")

    # Per-glyph detail when there's a mismatch
    orig_gc = Counter(orig_stats['glyphs'])
    edit_gc = Counter(edit_stats['glyphs'])
    glyph_diff = [(n, orig_gc[n], edit_gc[n])
                  for n in sorted(set(orig_gc) | set(edit_gc))
                  if orig_gc[n] != edit_gc[n]]
    if glyph_diff:
        print()
        print("  ── Glyph tag detail ─────────────────────────────────")
        for name, ov, ev in glyph_diff:
            desc = KNOWN_GLYPHS.get(name, '?')
            print(f"    ✗ [{name}] ({desc})  orig={ov}  edited={ev}  ({ev-ov:+d})")

    print()
    if all_ok:
        print("  ✓ All tag counts match — safe to recompress.")
    else:
        print("  ⚠ Tag mismatches detected.")
        print("    @o = italic/outside-voice — do NOT replace with spaces!")
        print("    [glyph] tags are font symbols — preserve name AND surrounding ruby!")
        print("    Ruby/@_/@p must be preserved exactly.")
        print("    ^ breaks change text flow — verify intentional changes.")
        print("    (thought) parentheses trigger italic in EN — keep them!")
        print("    BOLD does not exist in this engine — no bold markup to worry about.")
    print()


def usage():
    print(BANNER)
    print("  Commands:")
    print("    python3 ctd_tool.py  info         <file.ctd>")
    print("    python3 ctd_tool.py  decompress   <file.ctd>   [output.txt]")
    print("    python3 ctd_tool.py  compress     <input.txt>  [output.ctd]")
    print("    python3 ctd_tool.py  tags         <file.txt>")
    print("    python3 ctd_tool.py  validate     <original.txt>  <edited.txt>")
    print()
    print("  Examples:")
    print("    python3 ctd_tool.py  info         script_text_en.ctd")
    print("    python3 ctd_tool.py  decompress   script_text_en.ctd")
    print("    python3 ctd_tool.py  decompress   script_text_en.ctd  en_script.txt")
    print("    python3 ctd_tool.py  compress     en_script.txt       script_text_en.ctd")
    print("    python3 ctd_tool.py  tags         en_script.txt")
    print("    python3 ctd_tool.py  validate     en_script_orig.txt  en_script_edited.txt")
    print()
    print("  Script Tag Quick Reference:")
    print("    <text|ruby>           ruby/furigana or bilingual chant")
    print("    <text|@p-N/ruby>      ruby with horizontal pixel offset N")
    print("    <text|@_orig>         chant with hidden original-language marker")
    print("    ^                     soft line-break (no player click needed)")
    print("    @o                    ★ ITALIC outside-voice font  (line start only!)")
    print("    (text)                ★ ITALIC internal thought    (EN script only)")
    print("    [onpu]                ♪ music-note glyph")
    print("    [swel] [eywz]         rune glyphs ᛊ ᛇ  (inside ruby)")
    print("    [ansz] [ingz]         rune glyphs ᚨ ᛜ  (inside ruby)")
    print("    leading spaces        indentation = dialogue depth / channel")
    print("    BOLD                  ✗ NOT SUPPORTED — no bold tag in this engine")
    print("    Inline italic         ✗ NOT SUPPORTED — only @o and (...) trigger italic")
    print()


def main():
    if len(sys.argv) < 3:
        usage(); sys.exit(0)
    cmd = sys.argv[1].lower()
    if cmd == 'info':
        cmd_info(sys.argv[2])
    elif cmd in ('decompress', 'extract', 'decode'):
        cmd_decompress(sys.argv[2], sys.argv[3] if len(sys.argv) >= 4 else None)
    elif cmd in ('compress', 'pack', 'encode'):
        cmd_compress(sys.argv[2], sys.argv[3] if len(sys.argv) >= 4 else None)
    elif cmd == 'tags':
        cmd_tags(sys.argv[2])
    elif cmd == 'validate':
        if len(sys.argv) < 4:
            print("[ERROR] validate needs 2 .txt files"); sys.exit(1)
        cmd_validate(sys.argv[2], sys.argv[3])
    else:
        print(f"[ERROR] Unknown command: '{sys.argv[1]}'"); usage(); sys.exit(1)

if __name__ == '__main__':
    main()
