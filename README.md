# Dados de Eleicoes

Sistema Web em Python com Streamlit para consultar boletins de urna oficiais do TSE, calcular votos por cidade e comparar candidatos.

## Recursos

- Consulta dos boletins oficiais no Portal de Dados Abertos do TSE.
- Filtro por ano da eleicao antes do estado.
- Filtro por estado, turno, cargo e cidades.
- Comparacao de 1 a 5 candidatos para qualquer cargo selecionado.
- Suporte para 1 ou mais cidades no mesmo filtro.
- Funciona para deputado estadual, deputado federal, senador, governador e presidente.
- As selecoes feitas pelo usuario sao preservadas ao mudar cidade ou candidato.
- Grafico de barras com uma cor diferente para cada deputado/candidato.
- Exportacao do relatorio filtrado em PDF com totais nas barras e nas tabelas.
- Tabela com os votos calculados a partir dos boletins de urna.
- Substituicao automatica dos arquivos existentes de dados baixados/agregados.
- Execucao local via Docker.

## Como rodar com Docker

```powershell
docker compose up --build
```

Depois acesse:

```text
http://localhost:8501
```

## Como rodar sem Docker

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app/main.py
```

## Fonte dos dados

O sistema consulta a API CKAN do Portal de Dados Abertos do TSE:

```text
https://dadosabertos.tse.jus.br/api/3/action/package_show?id=resultados-ANO-boletim-de-urna
```

Cada combinacao de ano, estado e turno aponta para um ZIP oficial `bweb`.

Anos suportados nesta versao:

- 2024
- 2022
- 2020
- 2018

Os anos 2014 e 2016 tambem existem no portal, mas usam arquivos TXT sem cabecalho e exigem um parser proprio.

## Cache

Os arquivos baixados e agregados ficam em:

```text
data/cache/tse/
```

Essa pasta e ignorada pelo Git.

Por padrao, quando uma combinacao de ano, estado e turno e carregada, o sistema substitui os arquivos existentes em disco. Isso evita que um deploy no Render use dados antigos de um disco persistente.

Para reaproveitar arquivos ja existentes em disco, configure:

```text
TSE_OVERWRITE_EXISTING_FILES=false
```

## Estrutura

```text
app/
  main.py
  tse_client.py
data/
  .gitkeep
Dockerfile
docker-compose.yml
requirements.txt
```
