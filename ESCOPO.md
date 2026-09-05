# Escopo do Projeto — Dashboard (Excel → Python/Plotly)

> Preencher conforme as informações forem chegando.

## 1. Contexto e Objetivo
O objetivo deste projeto é criar um dashboard altamente parametrizável em plotly tendo como fonte o relatório de evolução anual de indicadores como unidades vendidas, volume em litros, receita e penetração das marcas e fabricantes de perfumes no território nacional

## 2. Dados de Origem (Excel)

- A origem dos dados está em um único arquivo na pasta "fonte" chamado "Vfinal_2026.07.06_Symrise_Worldpanel", na aba "Relatório Completo"; as demais abas devem ser ignorados.
- Detalhamento do cabeçalho da planilha: as linhas 1 até 4 devem ser ignoradas pois são apenas logotipos e textos, a linha 5 contém cabeçalhos de agrupamento, por exemplo, na linha 5, da coluna H até a coluna K, apresenta o cabeçalho "Volume (lts)" e na linha 6 estão os anos (Y2022 até Y2025) referentes a este indicador. Logo, para que possamos ter um único indicador, deve-se juntar as duas informações em uma única coluna, por exemplo: volume_Y2022 no momento de montagem dos dataframes. Esta lógica deve ser aplicada a todos os indicadores disponíveis na planilha.

Os indicadores disponíveis na planilha são:

- Volume (lts), 
- Unidades (absoluto) - valor nominal, inteiro
- Share Unidades (), - valor calculado, em percentual, uma casa decimal
- Valor sem Presentes (R$) - valor nominal, inteiro
- Valor com Presentes (R$) - valor nominal, inteiro
- Share Valor com Presentes % - valor calculado, em percentual, uma casa decimal.
- Compradores - valor nominal, inteiro
- Penetração - valor calculado, em percentual, uma casa decimal.
- Vol. por Comprador - valor calculado, uma casa decimal.
- Frequência - valor calculado, em percentual, uma casa decimal.
- Preço Médio (Litros) - valor calculado, uma casa decimal.
- Preço Médio (Unidades) - valor calculado, uma casa decimal.

Cada um deles possuem os dados de Y2022 até Y2025.

Já os dados de categorização compreendem estão na linha 6, da coluna A até G

- Região - C.Oeste Gde RJ Gde SP, Int.SP, Leste+IRJ, N+NE, Sudeste, Sul, T. Brasil; sendo que algumas são subregiões de outras conforme demonstrado: T. Brasil = Sudeste (Int.SP + Gde SP + Leste+IRJ + IRJ) + C.Oeste + N+NE + Sul. 
- Segmento - Total, Feminino, Infantil, Masculino, Unisex; sendo Total = (Feminino + Masculino + Infantil + Unisex)
- Fabricantes - 
    - Athenas Industrias
    - Avatim
    - Avon
    - Baruel
    - Bebe Natureza
    - Betulla
    - Betulla Cosmeticos
    - Boticário
    - Chimica Baruel
    - Ciclo Cosméticos
    - Coty
    - Flora
    - Giovanna baby
    - Granado
    - Hinode
    - Jequiti
    - Kanitz
    - Kenvue
    - Korres
    - Lattafa
    - Mahogany
    - Mary Kay
    - Muriel
    - Natura
    - Natura&CO
    - O. U. I
    - Outras (não é uma marca, é o totalizador por região e por segmento de "outras fabricantes" da coluna E)
    - Outros Fabricantes (não é uma marca, é o totalizador por cada região, já somados os segmentos, refere-se a coluna E de "outros fabricante" e da coluna G "T. Outros Fabricantes")
    - P&G
    - Phytoderm
    - Poran
    - Quimetal
    - Rugol
    - Suissa
    - Total (sempre sendo um totalizador)
    - We Pink (inclui WePink Cosméticos, padronizar no dataframe como WePink)
    
- Marca -

    - Athenas Industrias
    - Avatim
    - Avon
    - Baruel
    - Bebe Natureza
    - Betulla
    - Betulla Cosmeticos
    - Boticário
    - Ciclo Cosméticos
    - Coty
    - Eudora
    - Flora
    - Giovanna baby
    - Giovanna Baby Classic-Cli
    - Giovanna Baby Giby Borbolet.
    - Giovanna Baby-Cf
    - Granado
    - Granado Bebê
    - Hinode
    - Jequiti
    - Johnson
    - Kanitz
    - Kenvue
    - Korres
    - Lattafa
    - Mahogany
    - Mary Kay
    - Muriel
    - Natura
    - Natura&CO
    - O. Muriel-Cf
    - O. U. I
    - Outras (não é uma marca, é o totalizador por região e por segmento de "outras fabricantes" da coluna E)
    - Outros Fabricante (não é uma marca, é o totalizador por cada região, já somados os segmentos, refere-se a coluna E de "outros fabricante" e da coluna G "T. Outros Fabricantes")
    - P&G
    - Phebo
    - Phytoderm
    - Poran
    - Quem Disse Berenice
    - Quimetal
    - Rugol
    - Suissa
    - Total (sempre sendo um totalizador)
    - Turma da Xuxa-Cli
    - We Pink (inclui WePink Cosméticos, padronizar no dataframe como WePink)

- Classificação da linha:

    Fabricante
    Marca
    Outros Fabricante
    Outros Marca
    Outros Sub Marca
    Outros Variante
    Sub Marca
    Sub Variante
    Total (totalizadores)
    Variante
    
- Cód:
    - a coluna mais importante, pois aqui estão os agrupamentos das linhas, por exemplo:
        2	T. Subcategorias
        2.1	Feminino
        2.2	Masculino
        2.3	Infantil
        2.4	Unisex

    ou seja, os valores nominas das colunas já explicitadas anteriormente de Volume (lts), Unidades (absoluto) por exemplo, são a somatória dos índices, ou seja, 2 = soma (2.1 + 2.2 + 2.3 + 2.4) conforme a indexação do código. Outro exemplo: 
    6.1.3.1.7 = soma (6.1.3.1.7.1 + 6.1.3.1.7.2 + 6.1.3.1.7.3 + 6.1.3.1.7.4 + 6.1.3.1.7.5 + 6.1.3.1.7.6 + 6.1.3.1.7.7)

    - assim como os indicadores "Share Unidades ()" e "Share Valor com Presentes %" são calculados por pela relação do índice versus índice anterior, exemplo: share do 4.2 = volume do índice 4.2 / volume do índice 4 * 100, share do 4.2.3 = volume do índice 4.2.3 / volume do índice 4.2 * 100.

- Marcas:

    - Algumas marcas estão com sua descrição errada, exemplo: 'O. Muriel-Cf' deveria ser 'O. Muriel - Cf', 'Giovanna Baby-Cf' deveria ser 'Giovanna Baby - Cf', 'Turma da Xuxa-Cli' deveria ser 'Turma da Xuxa - Cli'.

- Volume aproximado de linhas/registros:

- valores nulos ou NA devem ser tratados como 0


## 3. Métricas e Visualizações (KPIs)

- Todas as categorias serão filtros isolados ou combinados,
- Os gráficos de evolução ano a ano de:
    - Volume (lts), 
    - Unidades (absoluto) - valor nominal, inteiro
    - Share Unidades (), - valor calculado, em percentual, uma casa decimal
    - Valor sem Presentes (R$) - valor nominal, inteiro
    - Valor com Presentes (R$) - valor nominal, inteiro
    - Share Valor com Presentes % - valor calculado, em percentual, uma casa decimal.
    - Compradores - valor nominal, inteiro

Devem seguir o layout de cores que será apresentado no arquivo "exemplo sankey e alluvium.png" que está na pasta "fonte"

Já os gráficos: 

- Penetração - valor calculado, em percentual, uma casa decimal.
- Vol. por Comprador - valor calculado, uma casa decimal.
- Frequência - valor calculado, em percentual, uma casa decimal.
- Preço Médio (Litros) - valor calculado, uma casa decimal.
- Preço Médio (Unidades) - valor calculado, uma casa decimal.

devem ser feitos em linha pois não se tratam de valores acumulados e empilhados, mas sim de linhas médias e não cumulativas.

- As cores por marca, submarca, fabricante, variante, sub variante e demais deverão ser padronizadas, ou seja, sempre que aparecer a marca A, independente da região ou segmento, ela deverá ter uma cor fixa, criar dicionário de cores para podermos alterar posteriormente.

## 4. Interatividade e Entrega
- Execução local (script Python) ou publicado (Dash, Streamlit, web app):
- Nível de interatividade (filtros, drill-down) ou visualização estática:
- dados fixos, não são retroalimentados, não mudarão quando o dashboard ficar pronto, se necessário ou melhor, transpor a base de dados para outra forma que não excel, como um bd local em mysql.

## 5. Requisitos Técnicos
- Ambiente de execução (máquinas locais sincronizadas via github)
- Responsável pela manutenção/atualização futura do código: quem estiver de plantão no momento (deixarei o notebook pronto para que qualquer um possa fazer alteração)
- Restrições de bibliotecas (pode ser ploty, ou qualquer biblioteca disponível no ambiente que entregue um bom controle de filtros, gráficos altamente customizáveis e com possibilidade de exportação da view para pdf em multiplas folhas A4 ou slides em pptx.)
