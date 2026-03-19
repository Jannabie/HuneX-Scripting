# WoTH Tools — Witch on the Holy Night File Tools

> **Moonlit Translation** — Tools pribadi untuk modding / translasi  
> Game: *Witch on the Holy Night (Mahoyo) Remastered* (Steam) — TYPE-MOON / HuneX

---

## 📸 Preview

| In-Game (Teks Indonesia) | Decoded MZP Image |
|:---:|:---:|
| ![In-Game](screenshots/ingame.png) | ![Decoded](screenshots/decoded.png) |

---

## 📦 Tools yang Tersedia

| File | Fungsi |
|------|--------|
| `hfa_tool.py` | Unpack / Repack arsip `.hfa` |
| `ctd_tool.py` | Decompress / Compress script teks `.ctd` (LenZuCompressor) |
| `cbg_tool.py` | Decode / Encode gambar `.cbg` (CompressedBG_MT) |
| `mzp_tool.py` | Decode / Encode gambar `.mzp` (MZP + MZX tiles) |

---

## 🔧 Requirements

```bash
pip install numpy Pillow
```

Python 3.10+ direkomendasikan.

---

## 📖 Cara Penggunaan

### HFA — Archive Packer/Unpacker

```bash
# Lihat isi archive
python hfa_tool.py list    data00300.hfa

# Ekstrak semua file
python hfa_tool.py unpack  data00300.hfa
python hfa_tool.py unpack  data00300.hfa  output_folder/

# Pack ulang folder menjadi .hfa
python hfa_tool.py repack  output_folder/  data00300_new.hfa
```

### CTD — Script Text (LenZuCompressor)

```bash
# Lihat info file
python ctd_tool.py info         script_text_en.ctd

# Ekstrak teks (CTD → TXT)
python ctd_tool.py decompress   script_text_en.ctd
python ctd_tool.py decompress   script_text_en.ctd  output.txt

# Pack teks kembali (TXT → CTD)
python ctd_tool.py compress     output.txt
python ctd_tool.py compress     output.txt  script_text_en.ctd
```

### CBG — Background Image (CompressedBG_MT)

```bash
# Lihat info file
python cbg_tool.py info    caution_en.cbg

# Decode ke PNG
python cbg_tool.py decode  caution_en.cbg
python cbg_tool.py decode  caution_en.cbg  output.png

# Encode PNG kembali ke CBG
python cbg_tool.py encode  output.png  caution_en.cbg
```

### MZP — Sprite / CG Image

```bash
# Lihat info file
python mzp_tool.py info    img0499.mzp

# Decode ke PNG
python mzp_tool.py decode  img0499.mzp
python mzp_tool.py decode  img0499.mzp  output.png

# Encode PNG kembali ke MZP
python mzp_tool.py encode  output.png  img0499.mzp
python mzp_tool.py encode  output.png  img0499.mzp  img0499_new.mzp
```

> **Catatan encode MZP:** File `.mzp` original wajib disertakan sebagai referensi parameter (tile size, bpp, palette type).

---

## 📂 Format Files

### `.hfa` — HuneX File Archive
Archive sederhana berisi beberapa file. Header berisi tabel offset per-entry.

```
Magic: HUNEXGGEFA10
Entry: [filename (96 bytes)] [rel_offset uint32] [size uint32]
```

### `.ctd` — Compressed Text Data (LenZuCompressor)
Script teks game dikompresi dengan algoritma LZ77 + Huffman custom HuneX.

```
Magic: LenZuCompressor\0
Codec: LSB-first Huffman + LZ77 (brLowBc=7, brBaseDist=2)
```

### `.cbg` — Compressed Background
Gambar background layar penuh. Dibagi menjadi stripe horizontal, setiap stripe dikompres dengan Huffman + delta filter.

```
Magic: CompressedBG_MT\0
Compression: LSB-first Huffman + zero-alternate + inverse delta
```

### `.mzp` — MZP Image Archive
Gambar sprite/CG dibagi menjadi tiles, setiap tile dikompres dengan MZX.

```
Magic: mrgd00
Tile compression: MZX (RLE + BACKREF + RINGBUF + LITERAL)
bmp_type: 0x01 (paletted), 0x08 (RGB24), 0x0B (RGBA32), 0x0C (HEP/per-tile palette)
```

---

## ⚠️ Disclaimer

Tools ini dibuat **khusus untuk keperluan translasi fan-made** (*Moonlit Translation*).  
Semua aset game adalah milik **TYPE-MOON** dan **HuneX**.  
Dilarang digunakan untuk tujuan komersial.

---

## 📜 Credits

- **Game**: *Witch on the Holy Night (Mahoyo) Remastered* (Steam)
- **Developer**: [TYPE-MOON](https://typemoon.com/) & [HuneX](http://www.hunex.co.jp/)
- **Tools**: [Moonlit Translation](https://github.com/) — Oby
- **Format Reference**: [loicfrance/mahoyo_tools](https://github.com/loicfrance/mahoyo_tools) (MIT License)

---

*Made with ❤️ for the Mahoyo community*
