#!/usr/bin/env python3
"""
MZP Image Tool v2 - HuneX Engine
Game  : Witch on the Holy Night (Mahoyo) Remastered - TYPE-MOON
Format: MZP archive + MZX-compressed tiles (supports all bmp_types)

Developed for: Oby
---------------------------------------------------------------
Supported bmp_type formats:
  0x01 depth 0x00/0x10 -> 4bpp paletted
  0x01 depth 0x01/0x11/0x91 -> 8bpp paletted
  0x08 depth 0x14 -> 24bpp RGB (RGB565 encoding)
  0x0B depth 0x14 -> 32bpp RGBA (RGB565 + alpha)
  0x0C depth 0x11 -> 32bpp RGBA via HEP sub-tiles (per-tile palette)

HEP tile format (bmp_type=0x0C):
  0x00: 'HEP\0' magic (4 bytes)
  0x04: file_size (4 bytes) = 0x20 + W*H + 0x400
  0x08: ? (8 bytes)
  0x10: ? (4 bytes)
  0x14: tile_width (4 bytes)
  0x18: tile_height (4 bytes)
  0x1C: transparency (4 bytes)
  0x20: pixel indices (W*H bytes)
  0x20+W*H: palette (256*4 bytes RGBA)

Requirements: pip install numpy Pillow
Usage:
  python mzp_tool.py  info    <file.mzp>
  python mzp_tool.py  decode  <file.mzp>   [output.png]
  python mzp_tool.py  encode  <input.png>  <original.mzp>  [output.mzp]
"""

import sys, struct
from io import BytesIO
from math import ceil
from pathlib import Path

def _check_deps():
    missing=[]
    try: import numpy
    except ImportError: missing.append('numpy')
    try: import PIL
    except ImportError: missing.append('Pillow')
    if not missing: return True
    print('\n  [!] Missing: '+', '.join(missing))
    ans=input('  Install now? (y/n): ').strip().lower()
    if ans=='y':
        import subprocess
        for p in missing: subprocess.call([sys.executable,'-m','pip','install',p])
        print('\n  Done! Run again.\n')
    else: print('\n  Run: pip install '+' '.join(missing)+'\n')
    return False

if not _check_deps(): sys.exit(1)

import numpy as np
from PIL import Image

# ── constants ────────────────────────────────────────────────
MZP_MAGIC   = b'mrgd00'
MZX_MAGIC   = b'MZX0'
HEP_MAGIC_I = int.from_bytes(b'HEP\x00','little')
HEP_HDR_SZ  = 0x20
HEP_PAL_SZ  = 0x400   # 256 * 4
SECTOR_SIZE = 0x800
ALIGNMENT   = 8

BANNER = (
    '\n'
    '+==========================================================+\n'
    '|         MZP Image Tool v2  -  HuneX Engine               |\n'
    '|      Witch on the Holy Night Remastered (TYPE-MOON)      |\n'
    '+==========================================================+\n'
)

# ── MZX ──────────────────────────────────────────────────────
class _RB:
    def __init__(self,sz,base=0):
        self._b=bytearray([base]*sz); self._p=0; self._s=sz
    def app(self,d):
        for b in d: self._b[self._p]=b; self._p=(self._p+1)%self._s
    def get(self,i,n): return bytes(self._b[(i+j)%self._s] for j in range(n))

def mzx_decompress(raw: bytes) -> bytes:
    src=BytesIO(raw); hdr=src.read(8)
    if hdr[:4]!=MZX_MAGIC: raise ValueError('Bad MZX magic: '+hdr[:4].hex())
    dsz=struct.unpack_from('<I',hdr,4)[0]
    out=bytearray(dsz); wp=0; rb=_RB(128); cc=0
    while wp<dsz and src.tell()<len(raw):
        fb=src.read(1)
        if not fb: break
        f=fb[0]; cmd=f&3; arg=f>>2
        if cc<=0: cc=0x1000
        if cmd==0:
            last=b'\x00\x00' if cc==0x1000 else bytes(out[wp-2:wp])
            ch=last*(arg+1); n=min(len(ch),dsz-wp); out[wp:wp+n]=ch[:n]; wp+=n; cc-=arg+1
        elif cmd==1:
            k=2*(src.read(1)[0]+1); ln=2*(arg+1); sp=wp-k
            buf=(bytes(out[sp:sp+k])*ceil(ln/k))[:ln] if k<ln else bytes(out[sp:sp+ln])
            n=min(ln,dsz-wp); out[wp:wp+n]=buf[:n]; wp+=n; cc-=arg+1
        elif cmd==2:
            rb2=rb.get(arg*2,2); n=min(2,dsz-wp); out[wp:wp+n]=rb2[:n]; wp+=n; cc-=1
        else:
            buf=src.read((arg+1)*2); n=min(len(buf),dsz-wp)
            out[wp:wp+n]=buf[:n]; wp+=n; rb.app(buf); cc-=arg+1
    return bytes(out)

def mzx_compress(data: bytes) -> bytes:
    """Level-0 literal compression."""
    words=np.frombuffer(data,dtype=np.uint8)
    if len(words)%2==1: words=np.append(words,0)
    words=words.view('<u2')
    out=bytearray(MZX_MAGIC+struct.pack('<I',len(data)))
    cur=0
    while cur<len(words):
        n=min(64,len(words)-cur)
        out.append(3|((n-1)<<2))
        out+=words[cur:cur+n].tobytes()
        cur+=n
    return bytes(out)

# ── MZP entry parsing ────────────────────────────────────────
def _parse_entries(data: bytes):
    nb=struct.unpack_from('<H',data,6)[0]; ds=8+nb*8; entries=[]
    for i in range(nb):
        so,bo,ss,sb=struct.unpack_from('<HHHH',data,8+i*8)
        ao=ds+so*SECTOR_SIZE+bo; size=sb
        while True:
            ss2=ceil((ao-ds+size)/SECTOR_SIZE)-so
            if ss2>=ss: break
            size+=SECTOR_SIZE
        entries.append((ao,size))
    return entries

# ── alpha fix ────────────────────────────────────────────────
def _fa(a): return ((a<<1)|(a>>6))&0xFF if not (a&0x80) else 0xFF
def _ufa(a): return a>>1
_np_fa  = np.vectorize(_fa)
_np_ufa = np.vectorize(_ufa)

# ── pixel format helpers ─────────────────────────────────────
def _rgb565_unpack(pq, offs):
    r=((pq&0xF800)>>8)|((offs>>5)&0x07)
    g=((pq&0x07E0)>>3)|((offs>>3)&0x03)
    b=((pq&0x001F)<<3)|(offs&0x07)
    return np.stack([r.astype(np.uint8),g.astype(np.uint8),b.astype(np.uint8)],axis=1)

def _rgb565_pack(rgb):
    off=((rgb[:,0]&0x07)<<5)|((rgb[:,1]&0x03)<<3)|(rgb[:,2]&0x07)
    r16=rgb.astype(np.uint16)
    pq=((r16[:,0]&0xF8)<<8)|((r16[:,1]&0xFC)<<3)|((r16[:,2]&0xF8)>>3)
    return pq, off

# ── HEP tile ─────────────────────────────────────────────────
def _hep_extract(raw: bytes, exp_w: int, exp_h: int) -> np.ndarray:
    """Decode a HEP tile -> (H, W, 4) RGBA array."""
    magic,fsz,_a,_b,_c,w,h,trans = struct.unpack_from('<IIIIIIII', raw)
    assert magic == HEP_MAGIC_I, f'Bad HEP magic 0x{magic:08x}'
    assert w == exp_w and h == exp_h, f'HEP dim mismatch {w}x{h} vs {exp_w}x{exp_h}'
    nb_px = w * h
    idx = np.frombuffer(raw, dtype=np.uint8, offset=HEP_HDR_SZ, count=nb_px)
    pal = np.frombuffer(raw, dtype=np.uint8, offset=HEP_HDR_SZ+nb_px,
                        count=HEP_PAL_SZ).copy().reshape(256,4)
    pal[:,3] = _np_fa(pal[:,3])
    return pal[idx].reshape(h, w, 4)

def _hep_build(pixels_rgba: np.ndarray, tw: int, th: int,
               transparency: int = 2) -> bytes:
    """Build a HEP tile from (H,W,4) RGBA pixels. Uses simple quantization."""
    from collections import Counter
    flat = pixels_rgba.reshape(-1, 4)
    # Build palette: unique colors up to 256
    # Simple approach: most frequent colors
    tuples = [tuple(p) for p in flat]
    counter = Counter(tuples)
    palette_colors = [c for c,_ in counter.most_common(256)]
    while len(palette_colors) < 256:
        palette_colors.append((0,0,0,0))
    pal_arr = np.array(palette_colors[:256], dtype=np.uint8)
    # Map each pixel to nearest palette entry
    pal_fixed = pal_arr.copy(); pal_fixed[:,3] = _np_ufa(pal_arr[:,3])
    indices = np.zeros(len(flat), dtype=np.uint8)
    for i,px in enumerate(flat):
        dists = np.sum((pal_arr.astype(np.int32)-px.astype(np.int32))**2, axis=1)
        indices[i] = np.argmin(dists)
    nb_px = tw * th
    fsz = HEP_HDR_SZ + nb_px + HEP_PAL_SZ
    hdr = struct.pack('<IIIIIIII',
        HEP_MAGIC_I, fsz, 0, 0, 0x10, tw, th, transparency)
    pal_write = pal_fixed.copy()
    return hdr + indices.tobytes() + pal_write.tobytes()

# ── tile decode dispatcher ────────────────────────────────────
def _decode_tile(raw: bytes, tw: int, th: int, bt: int, bd: int,
                 pal: np.ndarray | None) -> np.ndarray:
    """Decode one MZX-compressed tile -> pixel array."""
    td = mzx_decompress(raw)
    tile_sz = tw * th

    if bt == 0x01:
        bpp = 4 if bd in (0x00, 0x10) else 8
        if bpp == 4:
            arr = np.frombuffer(td, dtype=np.uint8)
            tile = np.stack([arr & 0x0F, arr >> 4], axis=1).flatten()[:tile_sz]
        else:
            tile = np.frombuffer(td, dtype=np.uint8)[:tile_sz]
        return pal[tile].reshape(th, tw, 4)

    elif bt in (0x08, 0x0B):
        bpp = 24 if bt == 0x08 else 32
        pq  = np.frombuffer(td, dtype='<u2', count=tile_sz)
        ofs = np.frombuffer(td, dtype=np.uint8, offset=tile_sz*2, count=tile_sz)
        px  = _rgb565_unpack(pq, ofs)
        if bpp == 32:
            al = np.frombuffer(td, dtype=np.uint8, offset=tile_sz*3, count=tile_sz)
            px = np.column_stack([px, al])
        return px.reshape(th, tw, 3 if bpp==24 else 4)

    elif bt == 0x0C:
        return _hep_extract(td, tw, th)

    else:
        raise ValueError(f'Unknown bmp_type=0x{bt:02x} depth=0x{bd:02x}')


# ── main decode ──────────────────────────────────────────────
def mzp_decode(data: bytes) -> Image.Image:
    entries = _parse_entries(data)
    e0 = data[entries[0][0]:entries[0][0]+entries[0][1]]
    W,H,tw,th,tx,ty,bt,bd,tc = struct.unpack_from('<HHHHHHHBB', e0)

    # Build palette for bmp_type=0x01
    pal = None
    if bt == 0x01:
        pal_sz = 16 if bd in (0x00, 0x10) else 256
        pal = np.frombuffer(e0, dtype=np.uint8, offset=16,
                            count=pal_sz*4).copy().reshape(pal_sz, 4)
        pal[:,3] = _np_fa(pal[:,3])
        if bd in (0x11, 0x91):
            for i in range(0, len(pal), 32):
                t=pal[i+8:i+16].copy(); pal[i+8:i+16]=pal[i+16:i+24]; pal[i+16:i+24]=t
        if pal_sz < 256:
            filler = np.repeat(np.array([[0,0,0,255]],dtype=np.uint8),256-pal_sz,axis=0)
            pal = np.vstack([pal, filler])

    # Output channels
    if bt in (0x08,):
        out_ch = 3
    else:
        out_ch = 4

    # bmp_type=0x01 adds +1 to image dims
    extra = 1 if bt == 0x01 else 0
    img_h = H - (ty-1)*tc*2 + extra
    img_w = W - (tx-1)*tc*2 + extra
    img = np.zeros((img_h, img_w, out_ch), dtype=np.uint8)

    for yi in range(ty):
        for xi in range(tx):
            idx = tx*yi + xi
            ao, sz = entries[idx+1]
            tile_px = _decode_tile(data[ao:ao+sz], tw, th, bt, bd, pal)

            sy = tc if (tc and yi>0) else 0
            ey = (th-tc) if (tc and yi<ty-1) else th
            sx = tc if (tc and xi>0) else 0
            ex = (tw-tc) if (tc and xi<tx-1) else tw
            rs = yi*(th-tc*2); cs = xi*(tw-tc*2)
            rc = min(img_h-rs-sy, ey-sy)
            cc = min(img_w-cs-sx, ex-sx)
            if rc > 0 and cc > 0:
                img[rs+sy:rs+sy+rc, cs+sx:cs+sx+cc] = tile_px[sy:sy+rc, sx:sx+cc]

    mode = 'RGB' if out_ch == 3 else 'RGBA'
    return Image.fromarray(img, mode)


# ── encode ───────────────────────────────────────────────────
def mzp_encode(img: Image.Image, orig_data: bytes) -> bytes:
    entries = _parse_entries(orig_data)
    e0 = orig_data[entries[0][0]:entries[0][0]+entries[0][1]]
    W,H,tw,th,tx,ty,bt,bd,tc = struct.unpack_from('<HHHHHHHBB', e0)

    extra = 1 if bt == 0x01 else 0
    img_h = H - (ty-1)*tc*2 + extra
    img_w = W - (tx-1)*tc*2 + extra

    # Prepare source pixels
    if bt == 0x08:   img = img.convert('RGB'); ch=3
    elif bt==0x01:   img = img.convert('RGBA'); ch=4
    else:            img = img.convert('RGBA'); ch=4
    img_px = np.array(img).reshape(img_h, img_w, ch)

    # For 0x01: load original palette
    pal_orig = None
    pal_fixed = None
    if bt == 0x01:
        pal_sz = 16 if bd in (0x00,0x10) else 256
        pal_raw = np.frombuffer(e0, dtype=np.uint8, offset=16,
                                count=pal_sz*4).copy().reshape(pal_sz,4)
        pal_fixed = pal_raw.copy(); pal_fixed[:,3]=_np_fa(pal_raw[:,3])
        if bd in (0x11,0x91):
            for i in range(0,len(pal_fixed),32):
                t=pal_fixed[i+8:i+16].copy(); pal_fixed[i+8:i+16]=pal_fixed[i+16:i+24]; pal_fixed[i+16:i+24]=t

    # Build new tile data
    new_tiles = []
    tile_trans = []

    for yi in range(ty):
        for xi in range(tx):
            sy = tc if (tc and yi>0) else 0
            ey = (th-tc) if (tc and yi<ty-1) else th
            sx = tc if (tc and xi>0) else 0
            ex = (tw-tc) if (tc and xi<tx-1) else tw
            rs = yi*(th-tc*2); cs = xi*(tw-tc*2)
            rc = min(img_h-rs-sy, ey-sy); cc = min(img_w-cs-sx, ex-sx)
            tile = np.zeros((th, tw, ch), dtype=np.uint8)
            if rc>0 and cc>0:
                tile[sy:sy+rc, sx:sx+cc] = img_px[rs+sy:rs+sy+rc, cs+sx:cs+sx+cc]

            if bt == 0x01:
                bpp = 4 if bd in (0x00,0x10) else 8
                # Map to palette indices
                flat = tile.reshape(-1,4)
                idx = np.zeros(len(flat), dtype=np.uint8)
                for i,px in enumerate(flat):
                    dists = np.sum((pal_fixed.astype(np.int32)-px.astype(np.int32))**2, axis=1)
                    idx[i] = np.argmin(dists)
                tile_bytes = idx.tobytes()
                # transparency
                a_vals = pal_fixed[idx,3]
                mn,mx = a_vals.min(),a_vals.max()
                trans = 0x00 if (mn==0 and mx==0) else (0x01 if mx<255 or mn<255 else 0x02)
                tile_trans.append(trans)

            elif bt in (0x08, 0x0B):
                rgb = tile[:,:,:3].reshape(-1,3)
                pq, of = _rgb565_pack(rgb)
                tile_bytes = pq.tobytes() + of.tobytes()
                if bt == 0x0B:
                    tile_bytes += tile[:,:,3].flatten().tobytes()
                tile_trans.append(0x02)

            elif bt == 0x0C:
                # HEP tile
                alpha = tile[:,:,3].flatten()
                mn,mx = alpha.min(),alpha.max()
                trans = 0x00 if (mn==0 and mx==0) else (0x01 if mx<255 or mn<255 else 0x02)
                tile_bytes = _hep_build(tile, tw, th, trans)
                tile_trans.append(trans)
            else:
                tile_bytes = tile.tobytes(); tile_trans.append(0x02)

            new_tiles.append(mzx_compress(tile_bytes))

    # Rebuild entry 0
    if bt == 0x01:
        pal_sz = 16 if bd in (0x00,0x10) else 256
        pal_end = 16 + pal_sz*4
        new_e0 = e0[:pal_end] + bytes(tile_trans)
    else:
        new_e0 = e0[:16+len(tile_trans)] if len(e0) > 16 else e0[:16] + bytes(tile_trans)
    # Keep exact original entry 0 header size up to tile_trans
    # (16 bytes header, then for 0x01: palette, then trans bytes)
    # For non-0x01: just header + trans
    hdr16 = e0[:16]
    if bt == 0x01:
        pal_bytes = e0[16:16+pal_sz*4]
        new_e0 = hdr16 + pal_bytes + bytes(tile_trans)
    else:
        new_e0 = hdr16 + bytes(tile_trans)

    # Assemble MZP file
    all_data = [new_e0] + new_tiles
    nb = len(all_data)
    # Build offsets
    offsets = []
    bodies = bytearray()
    for ed in all_data:
        offsets.append(len(bodies))
        bodies += ed
        pad = ALIGNMENT - len(ed) % ALIGNMENT if len(ed) % ALIGNMENT else 0
        bodies += b'\xff' * pad

    # Write header
    out = bytearray(MZP_MAGIC + struct.pack('<H', nb))
    for i, (ed, off) in enumerate(zip(all_data, offsets)):
        so = off // SECTOR_SIZE; bo = off % SECTOR_SIZE
        sz = len(ed); sb = sz & 0xFFFF
        ss = ceil((off+sz) / SECTOR_SIZE) - so
        out += struct.pack('<HHHH', so, bo, ss, sb)
    out += bodies
    return bytes(out)


# ── CLI ──────────────────────────────────────────────────────
def cmd_info(path):
    print(BANNER)
    data=Path(path).read_bytes()
    if not data.startswith(MZP_MAGIC): print('[ERROR] Not a MZP file'); sys.exit(1)
    entries=_parse_entries(data)
    e0=data[entries[0][0]:entries[0][0]+entries[0][1]]
    W,H,tw,th,tx,ty,bt,bd,tc=struct.unpack_from('<HHHHHHHBB',e0)
    bpp_map={(0x01,0x00):4,(0x01,0x10):4,(0x01,0x01):8,(0x01,0x11):8,(0x01,0x91):8,
             (0x08,0x14):24,(0x0B,0x14):32,(0x0C,0x11):32}
    bpp=bpp_map.get((bt,bd),'?')
    type_name={0x01:'Paletted',0x08:'RGB24/RGB565',0x0B:'RGBA32/RGB565',
               0x0C:'RGBA32/HEP-tile'}.get(bt,'Unknown')
    print('  File      : '+Path(path).name)
    print('  File size : '+str(len(data))+' bytes ('+f'{len(data)/1024/1024:.2f}'+' MB)')
    print('  Image     : '+str(W)+'x'+str(H)+' pixels ('+str(bpp)+'bpp '+type_name+')')
    print('  Tiles     : '+str(tx)+'x'+str(ty)+' = '+str(tx*ty)+' tiles of '+str(tw)+'x'+str(th))
    print('  bmp_type  : 0x'+format(bt,'02x')+'  bmp_depth: 0x'+format(bd,'02x'))
    print('  crop      : '+str(tc))
    print('  Entries   : '+str(len(entries))+' (1 header + '+str(len(entries)-1)+' tiles)')

def cmd_decode(mzp_path, out_path=None):
    print(BANNER)
    p=Path(mzp_path)
    if not p.exists(): print('[ERROR] Not found: '+mzp_path); sys.exit(1)
    data=p.read_bytes()
    print('  Input  : '+p.name+'  ('+str(len(data))+' bytes)')
    print('  Decoding...')
    img=mzp_decode(data)
    if out_path is None: out_path=str(p.with_suffix('.png'))
    img.save(out_path)
    print('  Output : '+out_path+'  ('+str(img.width)+'x'+str(img.height)+' '+img.mode+')')
    print()
    print('  Done!')

def cmd_encode(png_path, orig_mzp, out_path=None):
    print(BANNER)
    p=Path(png_path); op=Path(orig_mzp)
    if not p.exists(): print('[ERROR] Not found: '+png_path); sys.exit(1)
    if not op.exists(): print('[ERROR] Not found: '+orig_mzp); sys.exit(1)
    img=Image.open(str(p))
    orig=op.read_bytes()
    print('  Input    : '+p.name+'  ('+str(img.width)+'x'+str(img.height)+')')
    print('  Original : '+op.name)
    print('  Encoding...')
    result=mzp_encode(img,orig)
    if out_path is None: out_path=str(op)
    Path(out_path).write_bytes(result)
    print('  Output   : '+out_path+'  ('+str(len(result))+' bytes)')
    print()
    print('  Done!')

def usage():
    print(BANNER)
    print('  Commands:')
    print('    python mzp_tool.py  info    <file.mzp>')
    print('    python mzp_tool.py  decode  <file.mzp>    [output.png]')
    print('    python mzp_tool.py  encode  <input.png>   <original.mzp>  [output.mzp]')
    print()
    print('  Examples:')
    print('    python mzp_tool.py  info    img0499.mzp')
    print('    python mzp_tool.py  decode  img0499.mzp')
    print('    python mzp_tool.py  decode  img0499.mzp   output.png')
    print('    python mzp_tool.py  encode  output.png    img0499.mzp')
    print()

def main():
    if len(sys.argv)<3: usage(); sys.exit(0)
    cmd=sys.argv[1].lower()
    if cmd=='info': cmd_info(sys.argv[2])
    elif cmd in ('decode','extract'): cmd_decode(sys.argv[2],sys.argv[3] if len(sys.argv)>=4 else None)
    elif cmd in ('encode','pack','import'):
        if len(sys.argv)<4: print('[ERROR] encode needs <input.png> <original.mzp>'); sys.exit(1)
        cmd_encode(sys.argv[2],sys.argv[3],sys.argv[4] if len(sys.argv)>=5 else None)
    else: print('[ERROR] Unknown: '+sys.argv[1]); usage(); sys.exit(1)

if __name__=='__main__': main()
