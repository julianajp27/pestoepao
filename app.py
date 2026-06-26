from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from pymongo import MongoClient
from datetime import datetime, timedelta, timezone
from bson.objectid import ObjectId
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import random
import json
import os
from dotenv import load_dotenv

FUSO_BR = timezone(timedelta(hours=-3))

load_dotenv()

app = Flask(
    __name__,
    static_folder="static",
    template_folder="templates"
)
app.secret_key = 'pesto_e_pao_chave_secreta_super_segura'

# ==========================================
# 📊 FILTRO PERSONALIZADO DE MOEDA BRASILEIRA
# ==========================================
@app.template_filter('formata_moeda')
def formata_moeda(valor):
    try:
        # Transforma 5000.0 em "5,000.00", depois troca para "5.000,00"
        return f"{float(valor):,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    except (ValueError, TypeError):
        return "0,00"

# ==========================================
# CONFIGURAÇÃO DO BANCO DE DADOS (MONGODB)
# ==========================================
MONGO_URI = os.environ.get('MONGO_URI')

try:
    client = MongoClient(MONGO_URI)
    db = client['pesto_e_pao_db']
    produtos_col = db['produtos']
    insumos_col = db['insumos']
    clientes_col = db['clientes']
    caixa_col = db['caixa']
    usuarios_col = db['usuarios']
    print("🟢 Conexão com o MongoDB Atlas estabelecida com sucesso!")
    
    # 🔒 CRIAÇÃO OU ATUALIZAÇÃO DO USUÁRIO ADMIN
    admin_user = usuarios_col.find_one({"username": "pesto&pao"})
    if not admin_user:
        usuarios_col.insert_one({
            "username": "pesto&pao",
            "password": generate_password_hash("Pp223344*"),
            "email": "casapestoepao@gmail.com"
        })
        print("🟢 Usuário Admin 'pesto&pao' criado com sucesso!")
    else:
        usuarios_col.update_one(
            {"username": "pesto&pao"},
            {"$set": {"email": "casapestoepao@gmail.com"}}
        )

except Exception as e:
    print(f"🔴 Erro ao conectar ao MongoDB: {e}")

# ==========================================
# DECORATOR DE SEGURANÇA (Tranca as telas)
# ==========================================
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'usuario_logado' not in session:
            flash('Por favor, faça login para acessar o painel.', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# ==========================================
# ROTAS DE AUTENTICAÇÃO E RECUPERAÇÃO
# ==========================================
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = usuarios_col.find_one({"username": username})
        
        if user and check_password_hash(user['password'], password):
            session['usuario_logado'] = user['username']
            return redirect(url_for('dashboard'))
        else:
            flash('Usuário ou senha incorretos.', 'error')
            
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('usuario_logado', None)
    return redirect(url_for('login'))

@app.route('/esqueci_senha', methods=['POST'])
def esqueci_senha():
    username = request.form.get('username_recuperacao')
    user = usuarios_col.find_one({"username": username})
    
    if user:
        codigo_email = str(random.randint(100000, 999999))
        session['codigo_recuperacao'] = codigo_email
        session['usuario_recuperacao'] = username
        email_destino = user.get('email', 'casapestoepao@gmail.com')
        
        print("="*60)
        print(f"📧 MOCK E-MAIL ENVIADO PARA: {email_destino}")
        print(f"🔑 Seu código de recuperação da Pesto e Pão é: {codigo_email}")
        print("="*60)
        
        return "codigo_enviado"
    return "usuario_nao_encontrado"

@app.route('/redefinir_senha', methods=['POST'])
def redefinir_senha():
    codigo_digitado = request.form.get('codigo_sms')
    nova_senha = request.form.get('nova_senha')
    
    if 'codigo_recuperacao' in session and codigo_digitado == session['codigo_recuperacao']:
        username = session.get('usuario_recuperacao')
        usuarios_col.update_one(
            {"username": username},
            {"$set": {"password": generate_password_hash(nova_senha)}}
        )
        session.pop('codigo_recuperacao', None)
        session.pop('usuario_recuperacao', None)
        
        flash('Senha redefinida com sucesso! Faça login com a nova senha.', 'success')
        return redirect(url_for('login'))
    else:
        flash('Código de verificação inválido ou expirado.', 'error')
        return redirect(url_for('login'))

# ==========================================
# ROTAS DO SISTEMA (PROTEGIDAS)
# ==========================================

@app.route('/')
@login_required
def dashboard():
    total_clientes = clientes_col.count_documents({})
    mes_atual = datetime.now().month
    ano_atual = datetime.now().year
    vendas_gerais = list(caixa_col.find({"tipo": "entrada", "categoria": "Venda"}))
    faturamento_mes = sum(float(v.get('valor', 0)) for v in vendas_gerais if v.get('data_lancamento') and v.get('data_lancamento').month == mes_atual and v.get('data_lancamento').year == ano_atual)
            
    produtos = list(produtos_col.find())
    produtos_alerta = [p for p in produtos if float(p.get('quantidade', 0)) <= float(p.get('alerta_minimo', 0))]
    total_alertas = len(produtos_alerta)
    
    ultimas_vendas = list(caixa_col.find({"tipo": "entrada", "categoria": "Venda"}).sort("data_lancamento", -1).limit(5))

    meses_nomes_pt = {1: 'Jan', 2: 'Fev', 3: 'Mar', 4: 'Abr', 5: 'Mai', 6: 'Jun', 7: 'Jul', 8: 'Ago', 9: 'Set', 10: 'Out', 11: 'Nov', 12: 'Dez'}
    hoje = datetime.now()
    meses_labels = []
    
    for i in range(5, -1, -1):
        m = hoje.month - i
        y = hoje.year
        if m <= 0:
            m += 12
            y -= 1
        meses_labels.append(f"{meses_nomes_pt[m]}/{str(y)[2:]}")

    dados_grafico = {label: {'entradas': 0.0, 'saidas': 0.0} for label in meses_labels}
    todos_lancamentos = list(caixa_col.find())
    for item in todos_lancamentos:
        data_item = item.get('data_lancamento')
        if data_item:
            label = f"{meses_nomes_pt[data_item.month]}/{str(data_item.year)[2:]}"
            if label in dados_grafico:
                valor = float(item.get('valor', 0))
                if item.get('tipo') == 'entrada':
                    dados_grafico[label]['entradas'] += valor
                elif item.get('tipo') == 'saida':
                    dados_grafico[label]['saidas'] += valor

    valores_entradas = [dados_grafico[l]['entradas'] for l in meses_labels]
    valores_saidas = [dados_grafico[l]['saidas'] for l in meses_labels]

    return render_template('dashboard.html', total_clientes=total_clientes, faturamento_mes=faturamento_mes,
                           total_alertas=total_alertas, produtos_alerta=produtos_alerta[:5], ultimas_vendas=ultimas_vendas,
                           labels_grafico=json.dumps(meses_labels), entradas_grafico=json.dumps(valores_entradas), saidas_grafico=json.dumps(valores_saidas))

@app.route('/produtos')
@login_required
def produtos():
    return render_template('produtos.html', lista_produtos=list(produtos_col.find().sort("nome", 1)))

@app.route('/cadastrar_produto', methods=['POST'])
@login_required
def cadastrar_produto():
    produto_id = request.form.get('produto_id')
    dados_produto = {"nome": request.form.get('nome'), "quantidade": float(request.form.get('quantidade')), "preco": request.form.get('preco'), "data_producao": request.form.get('data_producao'), "data_validade": request.form.get('data_validade'), "desconto": request.form.get('desconto'), "alerta_minimo": float(request.form.get('alerta_minimo'))}
    try:
        if produto_id: produtos_col.update_one({'_id': ObjectId(produto_id)}, {'$set': dados_produto})
        else:
            dados_produto["data_cadastro"] = datetime.now()
            produtos_col.insert_one(dados_produto)
    except: pass
    return redirect(url_for('produtos'))

@app.route('/deletar_produto/<id>', methods=['POST'])
@login_required
def deletar_produto(id):
    try: produtos_col.delete_one({'_id': ObjectId(id)})
    except: pass
    return redirect(url_for('produtos'))

@app.route('/insumos')
@login_required
def insumos():
    return render_template('insumos.html', lista_insumos=list(insumos_col.find().sort("nome", 1)))

@app.route('/cadastrar_insumo', methods=['POST'])
@login_required
def cadastrar_insumo():
    insumo_id = request.form.get('insumo_id')
    nome_insumo = request.form.get('nome')
    custo_str = request.form.get('custo')
    dados_insumo = {"nome": nome_insumo, "quantidade": float(request.form.get('quantidade')), "unidade": request.form.get('unidade'), "custo": custo_str, "alerta_minimo": float(request.form.get('alerta_minimo'))}
    try:
        if insumo_id: insumos_col.update_one({'_id': ObjectId(insumo_id)}, {'$set': dados_insumo})
        else:
            dados_insumo["data_cadastro"] = datetime.now()
            insumos_col.insert_one(dados_insumo)
            valor_numerico = float(custo_str.replace('.', '').replace(',', '.'))
            caixa_col.insert_one({"tipo": "saida", "categoria": "Compra de Insumo", "descricao": f"Compra de estoque: {nome_insumo}", "valor": valor_numerico, "data_lancamento": datetime.now()})
    except: pass
    return redirect(url_for('insumos'))

@app.route('/deletar_insumo/<id>', methods=['POST'])
@login_required
def deletar_insumo(id):
    try: insumos_col.delete_one({'_id': ObjectId(id)})
    except: pass
    return redirect(url_for('insumos'))

@app.route('/clientes')
@login_required
def clientes():
    return render_template('clientes.html', lista_clientes=list(clientes_col.find().sort("nome", 1)))

@app.route('/cadastrar_cliente', methods=['POST'])
@login_required
def cadastrar_cliente():
    cliente_id = request.form.get('cliente_id')
    dados_cliente = {"nome": request.form.get('nome'), "telefone": request.form.get('telefone'), "email": request.form.get('email'), "endereco": request.form.get('endereco')}
    try:
        if cliente_id: clientes_col.update_one({'_id': ObjectId(cliente_id)}, {'$set': dados_cliente})
        else:
            dados_cliente["data_cadastro"] = datetime.now()
            clientes_col.insert_one(dados_cliente)
    except: pass
    return redirect(url_for('clientes'))

@app.route('/deletar_cliente/<id>', methods=['POST'])
@login_required
def deletar_cliente(id):
    try: clientes_col.delete_one({'_id': ObjectId(id)})
    except: pass
    return redirect(url_for('clientes'))

@app.route('/caixa')
@login_required
def caixa():
    lancamentos = list(caixa_col.find().sort("data_lancamento", -1))
    total_entradas = sum(float(l.get('valor', 0)) for l in lancamentos if l.get('tipo') == 'entrada')
    total_saidas = sum(float(l.get('valor', 0)) for l in lancamentos if l.get('tipo') == 'saida')
    return render_template('caixa.html', lista_lancamentos=lancamentos, total_entradas=total_entradas, total_saidas=total_saidas, saldo_atual=total_entradas - total_saidas)

@app.route('/cadastrar_lancamento_caixa', methods=['POST'])
@login_required
def cadastrar_lancamento_caixa():
    valor_numerico = float(request.form.get('valor').replace('.', '').replace(',', '.'))
    try: caixa_col.insert_one({"tipo": request.form.get('tipo'), "categoria": request.form.get('categoria'), "descricao": request.form.get('descricao'), "valor": valor_numerico, "data_lancamento": datetime.now()})
    except: pass
    return redirect(url_for('caixa'))

@app.route('/vendas')
@login_required
def vendas():
# Pega a hora atual de Brasília e remove a informação de fuso para virar uma data limpa
    agora_brasil = datetime.now(FUSO_BR).replace(tzinfo=None)
    hoje = agora_brasil.replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Agora a busca vai funcionar perfeitamente em qualquer hora do dia ou da noite
    vendas_de_hoje = list(caixa_col.find({"categoria": "Venda", "data_lancamento": {"$gte": hoje}}).sort("data_lancamento", -1))
    
    return render_template(
        'vendas.html', 
        lista_clientes=list(clientes_col.find().sort("nome", 1)), 
        lista_produtos=list(produtos_col.find().sort("nome", 1)), 
        vendas_hoje=vendas_de_hoje
    )

@app.route('/registrar_venda', methods=['POST'])
@login_required
def registrar_venda():
    produto_id = request.form.get('produto_id')
    cliente_id = request.form.get('cliente_id')
    qtd = float(request.form.get('quantidade'))
    pagamento = request.form.get('forma_pagamento')
    
    try:
        produto = produtos_col.find_one({'_id': ObjectId(produto_id)})
        
        # --- AJUSTE AQUI: Só busca o cliente se um ID válido for recebido ---
        cliente = None
        if cliente_id: 
            cliente = clientes_col.find_one({'_id': ObjectId(cliente_id)})
        # -------------------------------------------------------------------
        
        if produto:
            # Tratamento de preço e desconto
            preco_final = float(produto.get('preco').replace('.', '').replace(',', '.')) - (float(produto.get('desconto').replace('.', '').replace(',', '.')) if produto.get('desconto') else 0.0)
            
            # 1. BAIXA AUTOMÁTICA NO ESTOQUE
            produtos_col.update_one(
                {'_id': ObjectId(produto_id)}, 
                {'$set': {'quantidade': max(0.0, float(produto.get('quantidade', 0)) - qtd)}}
            )
            
            # Se não encontrou cliente (ou não foi enviado), vira Consumidor Final
            nome_cliente = cliente.get('nome') if cliente else "Consumidor Final"
            
            # Garante que a data salva no banco use o horário correto do Brasil
            agora_brasil = datetime.now(FUSO_BR).replace(tzinfo=None)
            
            # 2. CRÉDITO AUTOMÁTICO NO CAIXA (Agora com rastreio para cancelamento)
            caixa_col.insert_one({
                "tipo": "entrada", 
                "categoria": "Venda", 
                "descricao": f"Venda de {int(qtd)}x {produto.get('nome')} - Cliente: {nome_cliente} ({pagamento})", 
                "valor": preco_final * qtd, 
                "data_lancamento": agora_brasil,
                "produto_id": produto_id,  # NOVO: Necessário para o estorno
                "quantidade": qtd          # NOVO: Necessário para devolver ao estoque
            })
            
            flash(f'Venda de R$ {preco_final * qtd:.2f} registrada com sucesso!', 'success')
    except Exception as e:
        print(f"Erro ao registrar venda: {e}") # Ajuda a ver o erro no terminal se algo falhar
        flash('Erro ao registrar a venda.', 'error')
        
    return redirect(url_for('vendas'))

@app.route('/cancelar_venda/<id_venda>', methods=['POST'])
@login_required
def cancelar_venda(id_venda):
    try:
        # 1. Encontra o registro da venda no caixa
        venda = caixa_col.find_one({"_id": ObjectId(id_venda)})
        
        if venda:
            # 2. Verifica se a venda tem os dados de rastreio para devolver ao estoque
            if "produto_id" in venda and "quantidade" in venda:
                produtos_col.update_one(
                    {"_id": ObjectId(venda["produto_id"])},
                    {"$inc": {"quantidade": venda["quantidade"]}} # O $inc positivo soma de volta no estoque
                )
            
            # 3. Deleta o registro financeiro do caixa
            caixa_col.delete_one({"_id": ObjectId(id_venda)})
            flash('Venda cancelada! Valor removido do caixa e produto devolvido ao estoque.', 'success')
        else:
            flash('Venda não encontrada.', 'error')
            
    except Exception as e:
        print(f"Erro ao cancelar: {e}")
        flash('Erro ao cancelar a venda.', 'error')
        
    return redirect(url_for('vendas'))

@app.route('/chatbot')
@login_required
def chatbot():
    return render_template('chatbot.html')

# ==========================================
# 🤖 API DO CHATBOT (INTELIGÊNCIA INTERNA)
# ==========================================
@app.route('/api/chatbot', methods=['POST'])
@login_required
def api_chatbot():
    data = request.get_json() or {}
    mensagem = data.get('mensagem', '').lower().strip()
    
    # Resposta padrão caso ele não entenda a pergunta
    resposta = "Desculpe, ainda estou aprendendo! 🌿 Tente me perguntar sobre <b>vendas de hoje</b>, <b>faturamento do mês</b>, <b>custos</b>, <b>saldo</b>, <b>estoque</b> ou <b>clientes</b>."

    # Forçando o horário de Brasília para o robô não errar o dia
    from datetime import datetime, timedelta, timezone
    FUSO_BR = timezone(timedelta(hours=-3))
    agora_brasil = datetime.now(FUSO_BR)

    # 1. TELA DE CAIXA: VENDAS DO DIA (HOJE) -> Precisa vir ANTES da regra do mês!
    if ('hoje' in mensagem or 'do dia' in mensagem) and any(p in mensagem for p in ['venda', 'vendeu', 'faturamento']):
        vendas_hoje_lista = list(caixa_col.find({"tipo": "entrada", "categoria": "Venda"}))
        # Filtra apenas as vendas que têm o mesmo dia, mês e ano de hoje
        vendas_filtradas = [
            v for v in vendas_hoje_lista 
            if v.get('data_lancamento') and 
            v.get('data_lancamento').day == agora_brasil.day and 
            v.get('data_lancamento').month == agora_brasil.month and 
            v.get('data_lancamento').year == agora_brasil.year
        ]
        
        total_hoje = sum(float(v.get('valor', 0)) for v in vendas_filtradas)
        qtd_vendas = len(vendas_filtradas)
        total_formatado = f"{total_hoje:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
        
        if qtd_vendas > 0:
            resposta = f"Hoje nós já realizamos <b>{qtd_vendas} venda(s)</b>, totalizando um faturamento de <b>R$ {total_formatado}</b>! 🚀"
        else:
            resposta = "Ainda não tivemos nenhuma venda registrada no dia de hoje. Vamos torcer! 🤞"

    # 2. TELA DE CAIXA: FATURAMENTO / VENDAS (MÊS ATUAL)
    elif 'faturamento' in mensagem or 'vendeu' in mensagem or 'vendas' in mensagem:
        vendas_mes = list(caixa_col.find({"tipo": "entrada", "categoria": "Venda"}))
        total = sum(float(v.get('valor', 0)) for v in vendas_mes if v.get('data_lancamento') and v.get('data_lancamento').month == agora_brasil.month and v.get('data_lancamento').year == agora_brasil.year)
        total_formatado = f"{total:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
        resposta = f"O nosso faturamento com vendas neste mês está em <b>R$ {total_formatado}</b>! 💰"
        
    # 3. TELA DE CAIXA: CUSTOS / GASTOS (MÊS ATUAL)
    elif any(palavra in mensagem for palavra in ['custo', 'gasto', 'saida', 'saída', 'despesa']):
        todos_lancamentos = list(caixa_col.find({"tipo": "saida"}))
        total_custos = sum(float(l.get('valor', 0)) for l in todos_lancamentos if l.get('data_lancamento') and l.get('data_lancamento').month == agora_brasil.month and l.get('data_lancamento').year == agora_brasil.year)
        custos_formatado = f"{total_custos:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
        resposta = f"Os nossos custos e despesas totais deste mês estão em <b>R$ {custos_formatado}</b>. 💸"

    # 4. TELA DE CAIXA: SALDO GERAL ATUAL (ENTRADAS - SAÍDAS TOTAIS)
    elif 'saldo' in mensagem or 'caixa' in mensagem or 'financeiro' in mensagem:
        lancamentos = list(caixa_col.find())
        total_entradas = sum(float(l.get('valor', 0)) for l in lancamentos if l.get('tipo') == 'entrada')
        total_saidas = sum(float(l.get('valor', 0)) for l in lancamentos if l.get('tipo') == 'saida')
        saldo = total_entradas - total_saidas
        saldo_formatado = f"{saldo:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
        total_entradas_f = f"{total_entradas:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
        total_saidas_f = f"{total_saidas:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
        resposta = f"O saldo geral atual em caixa é de <b>R$ {saldo_formatado}</b> (Total Entradas: R$ {total_entradas_f} | Total Saídas: R$ {total_saidas_f}). 📊"

    # 5. TELAS DE ESTOQUE: ALERTAS DE FALTA (PRODUTOS E INSUMOS)
    elif 'falta' in mensagem or 'acabando' in mensagem or 'alerta' in mensagem:
        produtos = list(produtos_col.find())
        insumos = list(insumos_col.find())
        em_falta = [p['nome'] for p in produtos if float(p.get('quantidade', 0)) <= float(p.get('alerta_minimo', 0))]
        insumos_falta = [i['nome'] for i in insumos if float(i.get('quantidade', 0)) <= float(i.get('alerta_minimo', 0))]
        alertas = em_falta + insumos_falta
        if alertas:
            resposta = f"Atenção! ⚠️ Os seguintes itens estão precisando de reposição urgente: <b>{', '.join(alertas)}</b>."
        else:
            resposta = "Boas notícias! 🎉 O estoque está em dia. Nenhum produto ou insumo está abaixo do nível de alerta."

    # 6. TELA DE PRODUTOS: LISTAGEM / TOTAL DE PRODUTOS
    elif 'produto' in mensagem:
        total_produtos = produtos_col.count_documents({})
        lista_p = list(produtos_col.find().sort("nome", 1))
        nomes_p = [f"{p['nome']} ({int(p.get('quantidade', 0))} un)" for p in lista_p[:5]] # Mostra os primeiros 5
        extensao = f"<br>Exemplos em estoque: {', '.join(nomes_p)}" if nomes_p else ""
        resposta = f"Temos <b>{total_produtos} tipos de produtos</b> cadastrados no sistema.{extensao} 🥖"

    # 7. TELA DE INSUMOS: LISTAGEM / TOTAL DE INSUMOS
    elif 'insumo' in mensagem or 'materia' in mensagem or 'matéria' in mensagem:
        total_insumos = insumos_col.count_documents({})
        lista_i = list(insumos_col.find().sort("nome", 1))
        nomes_i = [f"{i['nome']} ({i.get('quantidade', 0)} {i.get('unidade', '')})" for i in lista_i[:5]] # Mostra os primeiros 5
        extensao = f"<br>Exemplos em estoque: {', '.join(nomes_i)}" if nomes_i else ""
        resposta = f"Temos <b>{total_insumos} insumos</b> registrados no banco.{extensao} 🌿"

    # 8. TELA DE CLIENTES: TOTAL DE CLIENTES
    elif 'cliente' in mensagem:
        total_clientes = clientes_col.count_documents({})
        resposta = f"Temos um total de <b>{total_clientes} clientes</b> cadastrados na nossa base! 👥"
        
    # 9. REGRAS DE AJUDA E SAUDAÇÕES
    elif any(palavra in mensagem for palavra in ['ajuda', 'fazer', 'bom dia', 'olá', 'oi', 'tarde', 'noite']):
        resposta = ("Olá! Eu sou a assistente da Pesto e Pão. Posso te ajudar a consultar seus dados rapidamente:<br><br>"
                    "👉 <b>Vendas e Caixa:</b> Pergunte sobre <i>'vendas de hoje'</i>, <i>'faturamento do mês'</i>, <i>'custos'</i> ou <i>'saldo'</i>.<br>"
                    "👉 <b>Estoque:</b> Pergunte por <i>'produtos'</i>, <i>'insumos'</i> ou o que está em <i>'falta'</i>.<br>"
                    "👉 <b>Clientes:</b> Pergunte por <i>'clientes cadastrados'</i>.")

    return jsonify({'resposta': resposta})

if __name__ == '__main__':
    app.run(debug=True)