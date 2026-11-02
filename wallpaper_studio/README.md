# Wallpaper Studio

Papel de parede por monitor no Windows: detecta as telas, mostra a disposição real
e deixa ajustar cada uma separadamente (ou uma imagem estendida em todas).

## Rodar no VS Code

1. Abra a pasta `wallpaper_studio` no VS Code (**Arquivo → Abrir pasta**).
2. No terminal do VS Code:
   ```powershell
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```
3. `Ctrl+Shift+P` → **Python: Select Interpreter** → escolha o `.venv`.
4. Aperte **F5** (configuração "Wallpaper Studio") ou rode `python main.py`.

## O que ele faz

| Recurso | Como |
|---|---|
| Detectar telas | Automático ao abrir, ao plugar/desplugar monitor, ou botão **Detectar telas** (F5) |
| Info de cada tela | Resolução física, Hz, escala do Windows (%), posição, tela principal |
| Identificar | Mostra o número grande em cada monitor, igual ao Windows |
| Modos do Windows | Preencher, Ajustar, Ampliar, Lado a lado, Centralizar — **por tela** |
| Estender | Botão **Estender em todas**: uma imagem cobrindo todas as telas |
| Ajuste fino | Escala, posição X/Y, rotação, perspectiva horizontal/vertical, espelhar, cor de fundo |
| Cor sólida | Botão **Cor sólida** remove a imagem e usa só a cor de fundo |
| Copiar | **Copiar p/ todas as telas** replica o ajuste da tela atual |
| Perfis | Salvar/Abrir perfil (.json) — ex.: "trabalho", "jogo" |
| Desfazer | Ctrl+Z (até 100 passos) |
| Aplicar | **Aplicar no Windows** (Ctrl+Enter) |

### Atalhos na área das telas

- **Arrastar** → mover a imagem · **Roda do mouse** → zoom
- **Ctrl + roda** ou **Ctrl + arrastar** → girar
- **Shift + arrastar** → perspectiva
- **Setas** → ajuste fino (Shift = 10×) · **+ / −** → escala · **R** → restaurar · **Tab** → próxima tela
- **Duplo clique** ou **arrastar uma imagem do Explorer** em cima da tela → trocar imagem

## Como o "Aplicar" funciona

O Windows não aceita perspectiva/rotação/posição por tela. Então o app monta **uma única
imagem do tamanho da área de trabalho virtual** (soma de todas as telas, em pixels físicos),
desenha o papel de parede de cada monitor no lugar exato dele e define essa imagem no
Windows com o estilo **Estender** (`WallpaperStyle = 22`). Resultado: cada tela recebe
exatamente o seu pedaço, com todos os ajustes.

- A imagem final fica em `%APPDATA%\WallpaperStudio\wallpaper_<n>.png`.
- As configurações ficam em `%APPDATA%\WallpaperStudio\config.json` (salvas sozinhas).
- O app também grava `JPEGImportQuality = 100` para o Windows não comprimir o papel de parede.

**Se mudar a resolução ou a posição de algum monitor nas Configurações do Windows,
clique em Aplicar de novo** — a imagem montada depende da disposição atual.

## Gerar um .exe (opcional)

```powershell
pip install pyinstaller
pyinstaller --noconsole --onefile --name WallpaperStudio main.py
```
O executável sai em `dist\WallpaperStudio.exe`.
