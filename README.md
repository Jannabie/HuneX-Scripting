# WoTH Tools

File tools for **Witch on the Holy Night (Mahoyo) Remastered** (Steam).  
Built for fan translation purposes — **Moonlit Translation**. Title image/ = examples.

---

## Preview

| In-Game (Indonesian) | Decoded MZP |
|:---:|:---:|
| ![ingame](https://i.imgur.com/1nPcH5G.png) | ![decoded](https://i.imgur.com/FE3c6MK.png) |

---

## Tools

| File | Description |
|------|-------------|
| `hfa_tool.py` | Unpack / Repack `.hfa` archives |
| `ctd_tool.py` | Decompress / Compress `.ctd` script files |
| `cbg_tool.py` | Decode / Encode `.cbg` background images |
| `mzp_tool.py` | Decode / Encode `.mzp` sprite / CG images |

---

## Requirements

```
pip install numpy Pillow
```

Python 3.10+

---

## Usage

### HFA

```bash
python hfa_tool.py list    data00300.hfa
python hfa_tool.py unpack  data00300.hfa
python hfa_tool.py repack  output_folder/  data00300_new.hfa
```

### CTD

```bash
python ctd_tool.py info         script_text_en.ctd
python ctd_tool.py decompress   script_text_en.ctd
python ctd_tool.py compress     output.txt  script_text_en.ctd
```

### CBG

```bash
python cbg_tool.py info    caution_en.cbg
python cbg_tool.py decode  caution_en.cbg
python cbg_tool.py encode  output.png  caution_en.cbg
```

### MZP

```bash
python mzp_tool.py info    img0499.mzp
python mzp_tool.py decode  img0499.mzp
python mzp_tool.py encode  output.png  img0499.mzp
```

> For `encode`, the original `.mzp` must be provided as a reference for tile parameters.

---

## File Formats

| Extension | Format | Compression |
|-----------|--------|-------------|
| `.hfa` | HuneX File Archive | None |
| `.ctd` | Script text | LenZuCompressor (LZ77 + Huffman, LSB-first) |
| `.cbg` | Background image | Huffman + zero-alternate + delta filter |
| `.mzp` | Sprite / CG image | MZX tiles (RLE + LZ + Huffman) |

---

## Credits

- Game & assets: **TYPE-MOON** / **HuneX**
- Format reference: [loicfrance/mahoyo_tools](https://github.com/loicfrance/mahoyo_tools)
- Tools: **Moonlit Translation**
