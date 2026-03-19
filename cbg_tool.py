#!/usr/bin/env python3
"""
CBG Image Tool - CompressedBG_MT (HuneX Engine)
Game  : Witch on the Holy Night (Mahoyo) Remastered - TYPE-MOON
Format: CompressedBG_MT

Developed for: Oby
---------------------------------------------------------------
CBG File Structure:
  0x00  16 bytes  Magic: "CompressedBG_MT\0"
  0x10   4 bytes  Width       (uint32 LE)
  0x14   4 bytes  Height      (uint32 LE)
  0x18   4 bytes  stripe_h    (uint32 LE)
  0x1c   4 bytes  bpp         (uint32 LE)  8/24/32
  0x20  16 bytes  Padding (zeroes)
  0x30   N*4 bytes Stripe offsets (uint32 LE x nb_stripes)
  ...    Stripe data

Per-Stripe Pipeline:
  Decode: Huffman(LSB-first,standard) -> zero-alt expand -> inverse delta -> BGR->RGB
  Encode: RGB->BGR -> forward delta -> zero-alt compress -> Huffman(LSB-first,standard)

Key facts (discovered through reverse engineering):
  - Bit reading: LSB-first (bit 0 = rightmost bit of byte)
  - Huffman traversal: standard (bit 0 -> left child, bit 1 -> right child)
  - Zero-alt: [nonzero_run][zero_run][nonzero_run]... starts nonzero
    If first byte is 0: prepend an empty (0-length) nonzero run first
  - Delta filter: px[y,x] += avg(px[y-1,x] + px[y,x-1])  uint16 intermediates

Requirements: pip install numpy Pillow

Usage:
  python3 cbg_tool.py  info    <file.cbg>
  python3 cbg_tool.py  decode  <file.cbg>   [output.png]
  python3 cbg_tool.py  encode  <input.png>  <output.cbg>  [stripe_h]  [bpp]
"""

import sys, struct, heapq
from math import ceil
from pathlib import Path

# ── dependency check ────────────────────────────────────────
def _check_deps():
    missing=[]
    try: import numpy
    except ImportError: missing.append('numpy')
    try: import PIL
    except ImportError: missing.append('Pillow')
    if not missing: return True
    print('\n  [!] Missing libraries: '+', '.join(missing))
    ans=input('  Install now? (y/n): ').strip().lower()
    if ans=='y':
        import subprocess
        for p in missing:
            subprocess.call([sys.executable,'-m','pip','install',p])
        print('\n  Done! Please run the script again.\n')
    else:
        print('\n  Run: pip install '+' '.join(missing)+'\n')
    return False

if not _check_deps(): sys.exit(1)

import numpy as np
from PIL import Image

# ── constants ────────────────────────────────────────────────
CBG_MAGIC = b'CompressedBG_MT\x00'
BANNER = (
    '\n'
    '+==========================================================+\n'
    '|        CBG Image Tool  -  CompressedBG_MT                |\n'
    '|      Witch on the Holy Night Remastered (TYPE-MOON)      |\n'
    '+==========================================================+\n'
)

# ── varint ──────────────────────────────────────────────────
def _rv(d, pos):
    val=0; shift=0
    while True:
        b=d[pos]; pos+=1; val|=(b&0x7f)<<shift; shift+=7
        if not (b&0x80): break
    return val, pos

def _wv(buf, val):
    while val>0x7f: buf.append((val&0x7f)|0x80); val>>=7
    buf.append(val)

# ── huffman ─────────────────────────────────────────────────
def _build_tree(sym_wt):
    counter=[0]
    def make(s,w): c=counter[0]; counter[0]+=1; return [w,c,s,None,None]
    heap=[make(s,w) for s,w in sym_wt if w>0]; heapq.heapify(heap)
    while len(heap)>1:
        a=heapq.heappop(heap); b=heapq.heappop(heap)
        c=counter[0]; counter[0]+=1
        heapq.heappush(heap,[a[0]+b[0],c,None,a,b])
    return heap[0] if heap else None

def _build_codes(root):
    codes={}
    def walk(n,c):
        if n[3] is None and n[4] is None: codes[n[2]]=c or '0'; return
        if n[3]: walk(n[3],c+'0')
        if n[4]: walk(n[4],c+'1')
    walk(root,''); return codes

# ── bit I/O (LSB-first) ──────────────────────────────────────
class _BR:
    def __init__(self,d,p,e): self.data=d;self.p=p;self.e=e;self.buf=0;self.cnt=0;self.x=False
    def bit(self):
        if self.cnt==0:
            if self.p>=self.e: self.x=True; return 0
            self.buf=self.data[self.p]; self.p+=1; self.cnt=8
        b=self.buf&1; self.buf>>=1; self.cnt-=1; return b

class _BW:
    def __init__(self): self.buf=0; self.cnt=0; self.out=bytearray()
    def bit(self,b):
        self.buf|=(b&1)<<self.cnt; self.cnt+=1
        if self.cnt==8: self.out.append(self.buf); self.buf=0; self.cnt=0
    def code(self,cs):
        for ch in cs: self.bit(int(ch))
    def flush(self):
        if self.cnt>0: self.out.append(self.buf)
    def get(self): self.flush(); return bytes(self.out)

# ── decode symbol (standard: bit0->left) ────────────────────
def _dsym(root, br):
    n=root
    while n[3] or n[4]: n=n[3] if br.bit()==0 else n[4]
    return n[2]

# ── stripe decode ────────────────────────────────────────────
def _decode_stripe(raw, offset, stripe_end, W, H, bpp):
    pos=offset
    huff_sz=struct.unpack_from('<I',raw,pos)[0]; pos+=4
    wts=[]
    for i in range(256): v,pos=_rv(raw,pos); wts.append(v)
    root=_build_tree([(i,w) for i,w in enumerate(wts)])
    br=_BR(raw,pos,stripe_end)
    # Pre-zero hout (matches BytesIO.truncate)
    hout=bytearray(huff_sz)
    for i in range(huff_sz):
        if br.x: break
        s=_dsym(root,br)
        if s is not None: hout[i]=s
    # Zero-alternate expand
    target=W*H*(bpp//8)
    exp=bytearray(target)
    hp=0; zeros=False; wp=0
    while hp<huff_sz and wp<target:
        v,hp2=_rv(hout,hp); v=min(v,target-wp)
        if zeros: wp+=v; hp=hp2
        else:
            avail=min(v,huff_sz-hp2) if hp2<huff_sz else 0
            exp[wp:wp+avail]=hout[hp2:hp2+avail]; wp+=v; hp=hp2+v
        zeros=not zeros
    # Inverse delta filter
    ch=bpp//8
    px=np.frombuffer(exp,dtype=np.uint8).copy().reshape(H,W,ch)
    for y in range(1,H): px[y,0,:]+=px[y-1,0,:]
    for x in range(1,W): px[0,x,:]+=px[0,x-1,:]
    for y in range(1,H):
        for x in range(1,W):
            px[y,x,:] += ((px[y-1,x,:].astype(np.uint16)+
                           px[y,x-1,:].astype(np.uint16))>>1).astype(np.uint8)
    # Channel swap BGR->RGB(A)
    if bpp==32: px[:,:,:3]=px[:,:,2::-1].copy()
    elif bpp==24: px[:,:,:]=px[:,:,::-1].copy()
    return px

# ── stripe encode ────────────────────────────────────────────
def _encode_stripe(pixels, W, H, bpp):
    px=pixels.copy()
    # Channel swap RGB(A)->BGR(A)
    if bpp==32: px[:,:,:3]=px[:,:,2::-1].copy()
    elif bpp==24: px[:,:,:]=px[:,:,::-1].copy()
    # Forward delta
    px=px.astype(np.int32)
    for y in range(H-1,0,-1):
        for x in range(W-1,0,-1):
            px[y,x]=(px[y,x]-((px[y-1,x]+px[y,x-1])>>1))&0xFF
    for y in range(H-1,0,-1): px[y,0]=(px[y,0]-px[y-1,0])&0xFF
    for x in range(W-1,0,-1): px[0,x]=(px[0,x]-px[0,x-1])&0xFF
    px=px.astype(np.uint8)
    # Zero-alternate compress (exact cbg.py logic)
    flat=px.flatten(); comp1=bytearray(); cursor=0; n=len(flat)
    if n>0 and flat[0]==0:
        _wv(comp1,0)  # empty non-zero run before leading zeros
    while cursor<n:
        i=cursor
        if flat[i]!=0:
            while i<n and flat[i]!=0: i+=1
            _wv(comp1,i-cursor); comp1.extend(flat[cursor:i].tobytes())
        else:
            while i<n and flat[i]==0: i+=1
            _wv(comp1,i-cursor)
        cursor=i
    # Huffman encode (LSB-first)
    freq=[0]*256
    for b in comp1: freq[b]+=1
    root=_build_tree([(i,w) for i,w in enumerate(freq)])
    codes=_build_codes(root)
    bw=_BW()
    for b in comp1: bw.code(codes[b])
    huff_stream=bw.get()
    out=bytearray()
    out+=struct.pack('<I',len(comp1))
    for i in range(256): _wv(out,freq[i])
    out+=huff_stream
    return bytes(out)

# ── public API ───────────────────────────────────────────────
def cbg_decode(raw: bytes) -> Image.Image:
    if raw[:16]!=CBG_MAGIC: raise ValueError('Not a CBG file (bad magic)')
    W=struct.unpack_from('<I',raw,0x10)[0]; H=struct.unpack_from('<I',raw,0x14)[0]
    SH=struct.unpack_from('<I',raw,0x18)[0]; bpp=struct.unpack_from('<I',raw,0x1c)[0]
    ns=ceil(H/SH)
    offs=list(struct.unpack_from('<'+str(ns)+'I',raw,0x30))
    ends=[offs[i+1] if i+1<ns else len(raw) for i in range(ns)]
    rows=[]
    for i in range(ns):
        sh=SH if i<ns-1 else (H%SH or SH)
        rows.append(_decode_stripe(raw,offs[i],ends[i],W,sh,bpp))
    full=np.vstack(rows) if len(rows)>1 else rows[0]
    mode={8:'L',24:'RGB',32:'RGBA'}.get(bpp,'RGBA')
    return Image.fromarray(full,mode)

def cbg_encode(img: Image.Image, original_cbg: bytes=None,
               stripe_h: int=60, bpp: int=32) -> bytes:
    if original_cbg is not None and original_cbg[:16]==CBG_MAGIC:
        stripe_h=struct.unpack_from('<I',original_cbg,0x18)[0]
        bpp=struct.unpack_from('<I',original_cbg,0x1c)[0]
    W,H=img.size
    mode={8:'L',24:'RGB',32:'RGBA'}.get(bpp,'RGBA')
    img=img.convert(mode); arr=np.array(img)
    ns=ceil(H/stripe_h)
    stripes=[]
    for i in range(ns):
        y0=i*stripe_h; sh=stripe_h if i<ns-1 else (H%stripe_h or stripe_h)
        stripes.append(_encode_stripe(arr[y0:y0+sh],W,sh,bpp))
    hdr_sz=0x30+ns*4
    offsets=[]; cur=hdr_sz
    for s in stripes: offsets.append(cur); cur+=len(s)
    out=bytearray()
    out+=CBG_MAGIC
    out+=struct.pack('<4I',W,H,stripe_h,bpp)
    out+=b'\x00'*16
    out+=struct.pack('<'+str(ns)+'I',*offsets)
    for s in stripes: out+=s
    return bytes(out)

# ── CLI ──────────────────────────────────────────────────────
def cmd_info(path):
    print(BANNER)
    raw=Path(path).read_bytes()
    if raw[:16]!=CBG_MAGIC: print('[ERROR] Not a CBG file'); sys.exit(1)
    W=struct.unpack_from('<I',raw,0x10)[0]; H=struct.unpack_from('<I',raw,0x14)[0]
    SH=struct.unpack_from('<I',raw,0x18)[0]; bpp=struct.unpack_from('<I',raw,0x1c)[0]
    ns=ceil(H/SH)
    offs=list(struct.unpack_from('<'+str(ns)+'I',raw,0x30))
    ends=[offs[i+1] if i+1<ns else len(raw) for i in range(ns)]
    mode={8:'Grayscale',24:'RGB',32:'RGBA'}.get(bpp,str(bpp)+'bpp')
    print('  File    : '+Path(path).name)
    print('  Size    : '+str(len(raw))+' bytes')
    print('  Image   : '+str(W)+' x '+str(H)+' ('+mode+')')
    print('  Stripes : '+str(ns)+'  (stripe_h='+str(SH)+')')
    for i,(o,e) in enumerate(zip(offs,ends)):
        print('    Stripe '+str(i)+': offset=0x'+format(o,'x')+'  size='+str(e-o))
    print('  Ratio   : '+format(W*H*(bpp//8)/len(raw),'.2f')+'x')

def cmd_decode(cbg_path, out_path=None):
    print(BANNER)
    p=Path(cbg_path)
    if not p.exists(): print('[ERROR] File not found: '+cbg_path); sys.exit(1)
    raw=p.read_bytes()
    print('  Input  : '+p.name+'  ('+str(len(raw))+' bytes)')
    img=cbg_decode(raw)
    if out_path is None: out_path=str(p.with_suffix('.png'))
    img.save(out_path)
    print('  Output : '+out_path+'  ('+str(img.width)+'x'+str(img.height)+' '+img.mode+')')
    print()
    print('  Done!')

def cmd_encode(png_path, cbg_path, stripe_h=None, bpp=None):
    print(BANNER)
    p=Path(png_path)
    if not p.exists(): print('[ERROR] File not found: '+png_path); sys.exit(1)
    img=Image.open(str(p))
    print('  Input  : '+p.name+'  ('+str(img.width)+'x'+str(img.height)+' '+img.mode+')')
    # Read original CBG params if target exists
    orig=None
    if Path(cbg_path).exists():
        orig_raw=Path(cbg_path).read_bytes()
        if orig_raw[:16]==CBG_MAGIC:
            orig=orig_raw
            sh2=struct.unpack_from('<I',orig,0x18)[0]
            bp2=struct.unpack_from('<I',orig,0x1c)[0]
            print('  Params : stripe_h='+str(sh2)+' bpp='+str(bp2)+'  (from existing CBG)')
    sh=int(stripe_h) if stripe_h else (struct.unpack_from('<I',orig,0x18)[0] if orig else 60)
    bp=int(bpp)      if bpp      else (struct.unpack_from('<I',orig,0x1c)[0] if orig else 32)
    print('  Encoding (stripe_h='+str(sh)+' bpp='+str(bp)+')...')
    result=cbg_encode(img,orig,sh,bp)
    Path(cbg_path).write_bytes(result)
    print('  Output : '+cbg_path+'  ('+str(len(result))+' bytes)')
    print('  Ratio  : '+format(img.width*img.height*(bp//8)/len(result),'.2f')+'x')
    print()
    print('  Done!')

def usage():
    print(BANNER)
    print('  Commands:')
    print('    python cbg_tool.py  info    <file.cbg>')
    print('    python cbg_tool.py  decode  <file.cbg>   [output.png]')
    print('    python cbg_tool.py  encode  <input.png>  <output.cbg>  [stripe_h]  [bpp]')
    print()
    print('  Examples:')
    print('    python cbg_tool.py  info    caution_en.cbg')
    print('    python cbg_tool.py  decode  caution_en.cbg')
    print('    python cbg_tool.py  decode  caution_en.cbg  output.png')
    print('    python cbg_tool.py  encode  output.png  caution_en.cbg')
    print()

def main():
    if len(sys.argv)<3: usage(); sys.exit(0)
    cmd=sys.argv[1].lower()
    if cmd=='info': cmd_info(sys.argv[2])
    elif cmd in ('decode','extract'): cmd_decode(sys.argv[2],sys.argv[3] if len(sys.argv)>=4 else None)
    elif cmd in ('encode','pack'):
        if len(sys.argv)<4: print('[ERROR] encode needs <input.png> <output.cbg>'); sys.exit(1)
        cmd_encode(sys.argv[2],sys.argv[3],
                   sys.argv[4] if len(sys.argv)>=5 else None,
                   sys.argv[5] if len(sys.argv)>=6 else None)
    else: print('[ERROR] Unknown: '+sys.argv[1]); usage(); sys.exit(1)

if __name__=='__main__': main()
