# Wallpaper Studio

Papel de parede **por monitor** no Windows. Detecta as telas, mostra a disposição real delas e deixa ajustar
cada uma separadamente (escala, posição, rotação, perspectiva, espelhar, cor de fundo) ou estender uma imagem
em todas. Salva perfis (ex.: "trabalho", "jogo") e tem desfazer (Ctrl+Z).

Como o Windows não aceita ajuste por tela, o app monta **uma única imagem do tamanho da área de trabalho
inteira**, com o pedaço certo de cada monitor, e aplica no modo **Estender**.

- Código e instruções completas: [wallpaper_studio/](wallpaper_studio/) (README dentro da pasta).
- Testes: `testes\rodar_testes.ps1` e `wallpaper_studio\testes\`.

## Rodar rápido
```powershell
cd wallpaper_studio
pip install -r requirements.txt
python main.py
```
