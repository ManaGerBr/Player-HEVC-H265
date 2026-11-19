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

## Executar pelo código-fonte

O arquivo `player_h265.py` pode ser executado com Python 3.8 ou superior. A execução direta requer VLC de 64 bits e o pacote `python-vlc`:

```powershell
pip install python-vlc
python player_h265.py
```

## Arquivos neste repositório

- `player_h265.py` — código-fonte Python fornecido.
- `Instalador_Player_H265.exe` — instalador Windows para usuários finais.
- `DESCRICAO_GITHUB.txt` — texto curto para o campo “About” do repositório.
- `SHA256SUMS.txt` — hash SHA-256 do instalador.

## Licença

Nenhuma licença foi informada para este projeto. Antes de aceitar contribuições ou permitir reutilização do código, adicione uma licença escolhida pelo autor.