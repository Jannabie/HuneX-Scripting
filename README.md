# WoTH Tools

Kumpulan tool untuk membongkar dan membangun ulang file-file dari game **Witch on the Holy Night (Mahoyo) Remastered** (Steam), dikembangkan untuk keperluan terjemahan fan **Moonlit Translation**.

---

## Perbandingan Hasil

| In-Game (Indonesia) | Decoded MZP |
|---|---|
| ![ingame](https://i.imgur.com/1nPcH5G.png) | ![decoded](https://i.imgur.com/FE3c6MK.png) |

---

## Struktur File

Game ini menggunakan empat format file proprietary yang masing-masing menangani jenis aset berbeda. Repo ini menyediakan tool Python untuk setiap formatnya.

| File | Format | Fungsi |
|---|---|---|
| `hfa_tool.py` | `.hfa` — HuneX File Archive | Unpack dan repack arsip utama game |
| `ctd_tool.py` | `.ctd` — Script text | Decompress dan compress file script dialog |
| `cbg_tool.py` | `.cbg` — Background / UI | Decode dan encode gambar background dan antarmuka |
| `mzp_tool.py` | `.mzp` — Sprite / CG | Decode dan encode gambar sprite dan CG |

Setiap format menggunakan algoritma kompresi tersendiri. `.ctd` menggunakan LenZuCompressor (LZ77 + Huffman, LSB-first). `.cbg` menggunakan Huffman dengan zero-alternate dan delta filter. `.mzp` menggunakan sistem tile MZX dengan kombinasi RLE, LZ, dan Huffman. `.hfa` tidak menggunakan kompresi sama sekali dan berfungsi murni sebagai kontainer arsip.

---

## Requirements

```bash
pip install numpy Pillow
```

Python 3.10 atau lebih baru.

---

## Cara Pakai

### HFA — Arsip Utama

```bash
python hfa_tool.py list    data00300.hfa          # Tampilkan daftar isi arsip
python hfa_tool.py unpack  data00300.hfa          # Ekstrak semua isi
python hfa_tool.py repack  output_folder/  data00300_new.hfa  # Pack ulang
```

### CTD — Script Dialog

```bash
python ctd_tool.py info         script_text_en.ctd        # Info header file
python ctd_tool.py decompress   script_text_en.ctd        # Ekstrak ke .txt
python ctd_tool.py compress     output.txt  script_text_en.ctd  # Compress kembali
```

### CBG — Background dan UI

```bash
python cbg_tool.py info    caution_en.cbg    # Info file
python cbg_tool.py decode  caution_en.cbg    # Decode ke .png
python cbg_tool.py encode  output.png  caution_en.cbg  # Encode kembali
```

### MZP — Sprite dan CG

```bash
python mzp_tool.py info    img0499.mzp       # Info file
python mzp_tool.py decode  img0499.mzp       # Decode ke .png
python mzp_tool.py encode  output.png  img0499.mzp   # Encode kembali
```

Folder `Title image/` berisi contoh file yang bisa digunakan untuk mencoba tool ini. Untuk perintah `encode`, file `.mzp` original **wajib disertakan** sebagai referensi parameter tile — tanpanya proses encode tidak bisa berjalan.

---

## Kredit

Format file dianalisis berdasarkan referensi dari [loicfrance/mahoyo_tools](https://github.com/loicfrance/mahoyo_tools). Game dan seluruh asetnya adalah milik **TYPE-MOON** / **HuneX**.

---

## Disclaimer

Tool ini dibuat untuk keperluan edukasi dan terjemahan fan. Gunakan sesuai aturan copyright dan Terms of Service dari game original.
