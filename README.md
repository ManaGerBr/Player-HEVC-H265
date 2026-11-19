# Player H.265

Player para Windows voltado a gravações H.265/HEVC de câmeras de segurança e DVRs. Também abre formatos comuns, como MP4, MKV, MOV, TS e AVI.

## Recursos

- Reprodução de gravações `.h265`, `.hevc`, `.265` e `.bin` de câmeras/DVRs.
- Abre também vídeos em `.mp4`, `.mkv`, `.mov`, `.ts`, `.m2ts`, `.avi` e `.webm`.
- Controles para pausar, avançar e voltar, ajustar volume, buscar no vídeo e usar tela cheia.
- Prepara fluxos H.265 sem contêiner em Matroska antes da reprodução; o vídeo é reorganizado sem recodificação.
- Converte o áudio G.711 A-law das gravações compatíveis para PCM durante a preparação.

## Instalação

1. Baixe `Instalador_Player_H265.exe` na seção **Releases**.
2. Execute o instalador e escolha se deseja criar atalhos.
3. Abra o Player H.265 pelo Menu Iniciar ou pela Área de Trabalho.

O instalador fornecido não está assinado digitalmente; o Windows pode mostrar um aviso de segurança ao abri-lo.

## Caso prefira o python ao invés do .exe você pode executalo pelo código-fonte

O arquivo `player_h265.py` pode ser executado com Python 3.8 ou superior. A execução direta requer VLC de 64 bits e o pacote `python-vlc`:

```powershell
pip install python-vlc
python player_h265.py
```

## Arquivos neste repositório

- `player_h265.py` — código-fonte Python fornecido.
- `Instalador_Player_H265.exe` — instalador Windows para usuários finais.
- `SHA256SUMS.txt` — hash SHA-256 do instalador.

- <img width="1067" height="691" alt="1" src="https://github.com/user-attachments/assets/3485afa5-7c2b-4804-9334-ac6163326f4f" />

<img width="1046" height="677" alt="2" src="https://github.com/user-attachments/assets/dcfc7f96-e715-4e5d-ad3d-ab7760f7de4b" />

<img width="1248" height="681" alt="3" src="https://github.com/user-attachments/assets/8a86bbbc-0ad1-41ed-bb17-4f373e424667" />



## Licença

Uma licença foi atribuída a este projeto de código aberto, permitindo que outras pessoas reutilizem o código.



-------
-------


## English

# H.265 Player

A Windows player for H.265/HEVC recordings from security cameras and DVRs. It also opens common formats such as MP4, MKV, MOV, TS, and AVI.

## Features

- Plays `.h265`, `.hevc`, `.265`, and `.bin` recordings from cameras and DVRs.
- Also opens `.mp4`, `.mkv`, `.mov`, `.ts`, `.m2ts`, `.avi`, and `.webm` videos.
- Controls for pausing, seeking, adjusting the volume, and switching to full screen.
- Prepares raw H.265 streams in a Matroska container before playback. The video is reorganized without re-encoding.
- Converts G.711 A-law audio in compatible recordings to PCM during preparation.

## Installation

1. Download `Instalador_Player_H265.exe` from the **Releases** section.
2. Run the installer and choose whether to create shortcuts.
3. Open H.265 Player from the Start Menu or Desktop.

The provided installer is not digitally signed, so Windows may display a security warning when you open it.

## Running from source with Python

If you prefer to use Python instead of the `.exe`, you can run the source code.

`player_h265.py` runs with Python 3.8 or later. Running it directly requires 64-bit VLC and the `python-vlc` package:

```powershell
pip install python-vlc
python player_h265.py
```

## Files in this repository

- `player_h265.py` — Python source code.
- `Instalador_Player_H265.exe` — Windows installer for end users.
- `SHA256SUMS.txt` — SHA-256 hash of the installer.

<img width="1067" height="691" alt="1" src="https://github.com/user-attachments/assets/3485afa5-7c2b-4804-9334-ac6163326f4f" />

<img width="1046" height="677" alt="2" src="https://github.com/user-attachments/assets/dcfc7f96-e715-4e5d-ad3d-ab7760f7de4b" />

<img width="1248" height="681" alt="3" src="https://github.com/user-attachments/assets/8a86bbbc-0ad1-41ed-bb17-4f373e424667" />

## License

A license has been assigned to this open-source project, allowing others to reuse the code.
