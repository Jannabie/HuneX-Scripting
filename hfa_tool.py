#!/usr/bin/env python3
"""
HFA Archive Tool - HuneX Engine
Game: Witch on the Holy Night (Mahoyo) Remastered - TYPE-MOON
Developer: HuneX

Developed for: Oby
-------------------------------------------------------------
Format Analysis Result:
  Magic       : HUNEXGGEFA10 (12 bytes)
  File Count  : uint32 little-endian @ 0x0C
  Entry Table : Starts @ 0x10, each entry = 128 (0x80) bytes
    [0x00~0x5F] Filename (null-terminated, max 96 chars)
    [0x60]      uint32 LE - Relative offset from data section
    [0x64]      uint32 LE - File size in bytes
    [0x68~0x7F] Padding (zeroes)
  Data Section: Immediately after entry table
-------------------------------------------------------------
Usage:
  List   : python3 hfa_tool.py list    <file.hfa>
  Unpack : python3 hfa_tool.py unpack  <file.hfa> [output_dir]
  Repack : python3 hfa_tool.py repack  <input_dir> <output.hfa>
"""

import struct
import sys
from pathlib import Path

MAGIC           = b'HUNEXGGEFA10'
HEADER_SIZE     = 0x10
ENTRY_SIZE      = 0x80
FILENAME_MAXLEN = 0x60
OFFSET_FIELD    = 0x60
SIZE_FIELD      = 0x64

BANNER = (
    "\n"
    "+==========================================================+\n"
    "|          HFA Archive Tool  -  HuneX Engine               |\n"
    "|      Witch on the Holy Night Remastered (TYPE-MOON)      |\n"
    "+==========================================================+\n"
)


def parse_hfa(data):
    if data[:12] != MAGIC:
        raise ValueError("Invalid HFA magic: got {!r}".format(data[:12]))
    num_files = struct.unpack_from('<I', data, 12)[0]
    table_end = HEADER_SIZE + num_files * ENTRY_SIZE
    if table_end > len(data):
        raise ValueError("Entry table exceeds file size")
    entries = []
    for i in range(num_files):
        base  = HEADER_SIZE + i * ENTRY_SIZE
        entry = data[base: base + ENTRY_SIZE]
        nul   = entry.find(b'\x00')
        name  = entry[:nul].decode('utf-8', errors='replace') if nul != -1 \
                else entry[:FILENAME_MAXLEN].decode('utf-8', errors='replace')
        rel_off = struct.unpack_from('<I', entry, OFFSET_FIELD)[0]
        size    = struct.unpack_from('<I', entry, SIZE_FIELD)[0]
        entries.append({'name': name, 'abs_offset': table_end + rel_off, 'size': size})
    return table_end, entries


def cmd_list(hfa_path):
    print(BANNER)
    path = Path(hfa_path)
    if not path.exists():
        print("[ERROR] File not found: {}".format(hfa_path)); sys.exit(1)
    data = path.read_bytes()
    table_end, entries = parse_hfa(data)
    print("  Archive : {}".format(path.name))
    print("  Size    : {:,} bytes ({:.1f} KB)".format(len(data), len(data)/1024))
    print("  Files   : {}".format(len(entries)))
    print("  Table   : ends at 0x{:x}".format(table_end))
    print()
    print("  {:>4}  {:<42}  {:>10}  {:>10}".format('#', 'Filename', 'Abs Offset', 'Size'))
    print("  {}  {}  {}  {}".format('-'*4, '-'*42, '-'*10, '-'*10))
    for i, e in enumerate(entries):
        print("  {:>4}  {:<42}  0x{:08x}  {:>10,}".format(
            i+1, e['name'], e['abs_offset'], e['size']))
    print()
    print("  Total packed data: {:,} bytes".format(sum(e['size'] for e in entries)))


def cmd_unpack(hfa_path, out_dir=None):
    print(BANNER)
    path = Path(hfa_path)
    if not path.exists():
        print("[ERROR] File not found: {}".format(hfa_path)); sys.exit(1)
    data = path.read_bytes()
    table_end, entries = parse_hfa(data)
    if out_dir is None:
        out_dir = path.stem
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    print("  Unpacking : {}".format(path.name))
    print("  Output    : {}".format(out.resolve()))
    print("  Files     : {}".format(len(entries)))
    print()
    extracted = []
    for i, e in enumerate(entries):
        name    = e['name']
        abs_off = e['abs_offset']
        size    = e['size']
        if abs_off + size > len(data):
            print("  [WARN] {}: out of bounds, skipping.".format(name))
            continue
        dst = out / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data[abs_off: abs_off + size])
        extracted.append(name)
        print("  [{:>4}/{}] {:<42}  {:>10,} bytes  OK".format(
            i+1, len(entries), name, size))
    # Write order manifest
    (out / '_hfa_order.txt').write_text('\n'.join(extracted) + '\n', encoding='utf-8')
    print()
    print("  Order manifest : _hfa_order.txt  (keeps original order on repack)")
    print("  Done! {} files extracted to: {}".format(len(extracted), out.resolve()))


def cmd_repack(input_dir, out_hfa):
    print(BANNER)
    src = Path(input_dir)
    if not src.exists() or not src.is_dir():
        print("[ERROR] Directory not found: {}".format(input_dir)); sys.exit(1)
    manifest = src / '_hfa_order.txt'
    if manifest.exists():
        names = [l.strip() for l in manifest.read_text(encoding='utf-8').splitlines() if l.strip()]
        files = [src / n for n in names]
        files = [f for f in files if f.exists()]
        print("  Order   : from _hfa_order.txt")
    else:
        files = sorted(f for f in src.iterdir() if f.is_file())
        print("  Order   : alphabetical (no _hfa_order.txt found)")
    if not files:
        print("[ERROR] No files to pack."); sys.exit(1)
    for f in files:
        if len(f.name.encode('utf-8')) >= FILENAME_MAXLEN:
            print("[ERROR] Filename too long: {}".format(f.name)); sys.exit(1)
    print("  Source  : {}".format(src.resolve()))
    print("  Output  : {}".format(out_hfa))
    print("  Files   : {}".format(len(files)))
    print()
    num_files  = len(files)
    table_end  = HEADER_SIZE + num_files * ENTRY_SIZE
    entry_table = bytearray(num_files * ENTRY_SIZE)
    chunks      = []
    rel_offset  = 0
    for i, f in enumerate(files):
        raw      = f.read_bytes()
        size     = len(raw)
        name_enc = f.name.encode('utf-8')
        entry = bytearray(ENTRY_SIZE)
        entry[0: len(name_enc)] = name_enc
        struct.pack_into('<I', entry, OFFSET_FIELD, rel_offset)
        struct.pack_into('<I', entry, SIZE_FIELD,   size)
        entry_table[i * ENTRY_SIZE: (i+1) * ENTRY_SIZE] = entry
        chunks.append(raw)
        print("  [{:>4}/{}] {:<42}  {:>10,} bytes  OK".format(
            i+1, num_files, f.name, size))
        rel_offset += size
    header = bytearray(HEADER_SIZE)
    header[0:12] = MAGIC
    struct.pack_into('<I', header, 12, num_files)
    out_data = bytes(header) + bytes(entry_table) + b''.join(chunks)
    out_path = Path(out_hfa)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(out_data)
    print()
    print("  Done! Archive written: {}".format(out_path.resolve()))
    print("  Total size: {:,} bytes ({:.1f} KB)".format(len(out_data), len(out_data)/1024))


def usage():
    print(BANNER)
    print("  Commands:")
    print("    python3 hfa_tool.py  list    <file.hfa>")
    print("    python3 hfa_tool.py  unpack  <file.hfa>  [output_dir]")
    print("    python3 hfa_tool.py  repack  <input_dir> <output.hfa>")
    print()
    print("  Examples:")
    print("    python3 hfa_tool.py  list    data00300.hfa")
    print("    python3 hfa_tool.py  unpack  data00300.hfa")
    print("    python3 hfa_tool.py  unpack  data00300.hfa  extracted/")
    print("    python3 hfa_tool.py  repack  data00300/     data00300_new.hfa")
    print()


def main():
    if len(sys.argv) < 3:
        usage(); sys.exit(0)
    cmd = sys.argv[1].lower()
    if cmd == 'list':
        cmd_list(sys.argv[2])
    elif cmd == 'unpack':
        cmd_unpack(sys.argv[2], sys.argv[3] if len(sys.argv) >= 4 else None)
    elif cmd == 'repack':
        if len(sys.argv) < 4:
            print("[ERROR] repack requires: <input_dir> <output.hfa>")
            usage(); sys.exit(1)
        cmd_repack(sys.argv[2], sys.argv[3])
    else:
        print("[ERROR] Unknown command: '{}'".format(sys.argv[1]))
        usage(); sys.exit(1)

if __name__ == '__main__':
    main()
