from cnpj_tool.parser import parse_company_page


HTML = """
<html>
  <head><title>Hipermercado Marques Center 03541629000137 Diamantina</title></head>
  <body>
    <main>
      <h1>Hipermercado Marques Center Organizacoes Marques Center LTDA 03.541.629/0001-37</h1>
      <h2>Informações de Registro</h2>
      CNPJ: 03.541.629/0001-37 - 03541629000137
      Razão Social: Organizacoes Marques Center LTDA
      Nome Fantasia: Hipermercado Marques Center
      Data da Abertura: 08/12/1999
      Porte: Sem Enquadramento
      Natureza Jurídica: Sociedade Empresária Limitada
      Opção pelo MEI: Não
      Opção pelo Simples: Não
      Capital Social: R$ 3.000.000,00
      Tipo: Matriz
      Situação: Ativa
      Data Situação Cadastral: 18/10/2003
      <h2>Contatos</h2>
      E-mail: fi****@****.com.br
      Telefone(s):<br>(38) 353****-****
      <h2>Localização</h2>
      Logradouro: Avenida Silvio Felicio dos Santos, 755
      Bairro: Bom Jesus
      CEP: 39100-000
      Município: <a>Diamantina</a>
      Estado: <a>Minas Gerais</a>
      Para correspondência:
      <h2>Atividades - CNAES</h2>
      Principal: 47.11-3-02 - Comércio varejista de mercadorias em geral
      Secundária(s): 47.51-2-01 - Comércio varejista especializado
      <h2>Quadro de Sócios e Administradores</h2>
      Carlos Marques Moreira - Sócio-Administrador<br>
      Poliana Aparecida Moreira - Sócio-Administrador<br>
      Qualificação do responsável pela empresa: Sócio-Administrador
      <h2>Sobre</h2>
      A empresa Hipermercado Marques Center de CNPJ 03.541.629/0001-37 está localizada em Diamantina.
      <h2>Filiais</h2>
      Total de 3 filiais.
      <a href="/03541629000218">Organizacoes Marques Center LTDA - 03.541.629/0002-18</a> (MG, Diamantina)
    </main>
  </body>
</html>
"""


def test_parse_company_page_extracts_core_fields_and_qsa():
    company = parse_company_page(HTML, "https://cnpj.biz/03541629000137")

    assert company.cnpj == "03541629000137"
    assert company.legal_name == "Organizacoes Marques Center LTDA"
    assert company.trade_name == "Hipermercado Marques Center"
    assert company.status == "Ativa"
    assert company.city == "Diamantina"
    assert company.state == "Minas Gerais"
    assert company.primary_cnae.startswith("47.11-3-02")
    assert company.responsible_qualification == "Sócio-Administrador"
    assert [candidate.name for candidate in company.candidates] == [
        "Carlos Marques Moreira",
        "Poliana Aparecida Moreira",
    ]
    assert company.branch_count == 3
    assert company.branches[0].cnpj == "03541629000218"


def test_parse_company_page_extracts_represented_administrator_candidate():
    html = """
    <main>
      <h1>Ax Incorporadora LTDA - 12.991.582/0001-02</h1>
      <h2>Informações de Registro</h2>
      CNPJ: 12.991.582/0001-02 - 12991582000102 Razão Social: Ax Incorporadora LTDA Situação: Ativa
      <h2>Quadro de Sócios e Administradores</h2>
      Rodex Investimentos LTDA - CNPJ: 32915571000142 - Sócio Representado por Eduardo Almeida Santos - Administrador<br>
      Qualificação do responsável pela empresa: Sócio-Administrador
    </main>
    """

    company = parse_company_page(html, "https://cnpj.biz/12991582000102")

    assert ("Eduardo Almeida Santos", "Administrador") in [
        (candidate.name, candidate.role) for candidate in company.candidates
    ]
