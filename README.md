# MagalBET — deploy no Vercel

No Vercel o Flask roda como **função serverless** (não há servidor fixo,
`gunicorn`, `Procfile` nem `render.yaml`). Todo o tráfego é roteado para
`app.py`, que serve o `index.html` e os endpoints `/api/*`.

## Estrutura — tudo na RAIZ do repositório

```
(raiz do repo)
├── app.py             # função Flask (site + /api/apostadores + /api/placar)
├── index.html         # front-end
├── requirements.txt   # Flask, flask-cors, requests  (SEM gunicorn)
├── vercel.json        # manda todas as rotas para app.py
└── .gitignore
```

> Se você já tinha `Procfile` e `render.yaml` do deploy no Render, **apague-os** —
> o Vercel não usa, e podem confundir.

## Passo a passo

1. Coloque estes 4 arquivos na raiz do repositório no GitHub.
2. No Vercel: **Add New → Project**, importe o repo.
3. Deixe as configurações no padrão e clique **Deploy**.
   (O `vercel.json` já cuida do build e do roteamento.)
4. A planilha precisa estar como **"Qualquer pessoa com o link → Leitor"**.
5. (Opcional) Em **Settings → Environment Variables**, defina `SHEET_ID`
   e/ou `SHEET_GID` se quiser apontar para outra planilha/aba.

## Rodar local (opcional)

```bash
pip install -r requirements.txt
python app.py          # http://localhost:5000
```
Ou, com a CLI do Vercel, `vercel dev` para simular o ambiente serverless.

## Pontos de atenção do serverless (Vercel Hobby)

- **Sem estado entre chamadas:** o cache em memória do `app.py` não persiste
  entre invocações (cada request pode ser uma instância nova). Não quebra nada —
  só busca a planilha/ESPN com mais frequência. O front continua atualizando
  o placar a cada 45s e a planilha a cada 3 min.
- **Cold start:** a primeira chamada após ociosidade pode demorar 1–2s.
- **Timeout:** funções no plano grátis têm limite curto (~10s). As chamadas à
  planilha e à ESPN têm timeout de 8s no código, então ficam dentro do limite.
- Se a API falhar, o front tem fallback: tenta planilha + ESPN direto e, em
  último caso, usa a lista local embutida.
