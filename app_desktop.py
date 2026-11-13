import threading
import webbrowser
import uvicorn
import sqlite3
import tkinter as tk
from tkinter import messagebox, ttk, filedialog
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, date
import openpyxl

# --- 1. BANCO DE DADOS SQLITE CORPORATIVO ---
DB_NAME = "wms_database.db"

def inicializar_banco():
    conexao = sqlite3.connect(DB_NAME)
    cursor = conexao.cursor()

    # Usuários e Perfis
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            senha TEXT NOT NULL,
            cargo TEXT NOT NULL
        )
    """)

    # Cadastro Mestre de Produtos
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS produtos_cadastro (
            sku TEXT PRIMARY KEY,
            descricao TEXT NOT NULL,
            categoria TEXT,
            peso_unitario REAL
        )
    """)

    # Parâmetros de Endereçamento
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS enderecos_config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rua TEXT NOT NULL,
            predio TEXT NOT NULL,
            nivel TEXT NOT NULL,
            apartamento TEXT NOT NULL,
            tipo_capacidade TEXT
        )
    """)

    # Estoque Físico / Lotes
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS estoque (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sku TEXT NOT NULL,
            descricao TEXT NOT NULL,
            lote TEXT NOT NULL,
            quantidade INTEGER NOT NULL,
            endereco TEXT NOT NULL,
            data_validade TEXT
        )
    """)

    # Transações e Auditoria
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transacoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo TEXT NOT NULL,
            sku TEXT,
            quantidade INTEGER,
            usuario TEXT,
            timestamp TEXT NOT NULL
        )
    """)

    # Backlog Cross-Docking
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pedidos_pendentes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pedido_id TEXT NOT NULL,
            sku TEXT NOT NULL,
            quantidade INTEGER NOT NULL
        )
    """)

    # Usuário Admin padrão
    cursor.execute("SELECT COUNT(*) FROM usuarios")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO usuarios (username, senha, cargo) VALUES (?, ?, ?)", ("admin", "123456", "Admin"))
        cursor.execute("INSERT INTO usuarios (username, senha, cargo) VALUES (?, ?, ?)", ("operador", "123456", "Operador"))

    conexao.commit()
    conexao.close()

inicializar_banco()


# --- 2. BACKEND FASTAPI ---
app = FastAPI(title="WMS Enterprise Completo")

class ProdutoRecebimento(BaseModel):
    sku: str
    descricao: str
    lote: str
    quantidade: int
    endereco: str
    data_validade: Optional[date] = None
    usuario: Optional[str] = "Sistema"

class MovimentacaoSeparacao(BaseModel):
    sku: str
    quantidade_requerida: int
    pedido_id: str
    estrategia: str = "FEFO"
    usuario: Optional[str] = "Sistema"

@app.post("/api/v1/recebimento")
def registrar_recebimento(item: ProdutoRecebimento):
    conexao = sqlite3.connect(DB_NAME)
    cursor = conexao.cursor()
    
    quantidade_restante = item.quantidade
    acoes_cross_docking = []
    
    cursor.execute("SELECT id, pedido_id, quantidade FROM pedidos_pendentes WHERE sku = ?", (item.sku,))
    pedidos = cursor.fetchall()
    
    for ped_id, pedido_codigo, qtd_ped in pedidos:
        if quantidade_restante > 0:
            alocado = min(qtd_ped, quantidade_restante)
            nova_qtd_ped = qtd_ped - alocado
            quantidade_restante -= alocado
            
            if nova_qtd_ped == 0:
                cursor.execute("DELETE FROM pedidos_pendentes WHERE id = ?", (ped_id,))
            else:
                cursor.execute("UPDATE pedidos_pendentes SET quantidade = ? WHERE id = ?", (nova_qtd_ped, ped_id))
                
            acoes_cross_docking.append({"pedido_id": pedido_codigo, "qtd": alocado})
            cursor.execute("INSERT INTO transacoes (tipo, sku, quantidade, usuario, timestamp) VALUES (?, ?, ?, ?, ?)",
                           ("CROSS_DOCKING", item.sku, alocado, item.usuario, datetime.now().isoformat()))

    if quantidade_restante > 0:
        cursor.execute("SELECT id, quantidade FROM estoque WHERE sku = ? AND lote = ? AND endereco = ?", 
                       (item.sku, item.lote, item.endereco))
        reg_existente = cursor.fetchone()
        
        if reg_existente:
            novo_saldo = reg_existente[1] + quantidade_restante
            cursor.execute("UPDATE estoque SET quantidade = ? WHERE id = ?", (novo_saldo, reg_existente[0]))
        else:
            cursor.execute("""
                INSERT INTO estoque (sku, descricao, lote, quantidade, endereco, data_validade)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (item.sku, item.descricao, item.lote, quantidade_restante, item.endereco, str(item.data_validade) if item.data_validade else None))

    cursor.execute("INSERT INTO transacoes (tipo, sku, quantidade, usuario, timestamp) VALUES (?, ?, ?, ?, ?)",
                   ("RECEBIMENTO", item.sku, item.quantidade, item.usuario, datetime.now().isoformat()))

    conexao.commit()
    conexao.close()
    return {"mensagem": "Recebimento processado!", "cross_docking": acoes_cross_docking, "estoque_adicionado": quantidade_restante}

@app.get("/api/v1/estoque")
def consultar_estoque():
    conexao = sqlite3.connect(DB_NAME)
    cursor = conexao.cursor()
    cursor.execute("SELECT sku, descricao, lote, quantidade, endereco, data_validade FROM estoque")
    rows = cursor.fetchall()
    conexao.close()
    return {"itens": [{"sku": r[0], "descricao": r[1], "lote": r[2], "quantidade": r[3], "endereco": r[4], "data_validade": r[5]} for r in rows]}

def rodar_servidor():
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")


# --- 3. TELA DE LOGIN ---
class LoginWindow:
    def __init__(self, root):
        self.root = root
        self.root.title("WMS Enterprise - Login")
        self.root.geometry("400x320")
        self.root.config(bg="#f0f2f5")
        self.root.resizable(False, False)

        tk.Label(root, text="🔐 WMS Enterprise Core", font=("Arial", 14, "bold"), bg="#f0f2f5", fg="#1f2937").pack(pady=20)

        form = tk.Frame(root, bg="#f0f2f5", padx=20, pady=10)
        form.pack()

        tk.Label(form, text="Usuário:", bg="#f0f2f5", font=("Arial", 10)).grid(row=0, column=0, sticky="w", pady=5)
        self.user_entry = tk.Entry(form, width=25, font=("Arial", 11))
        self.user_entry.grid(row=0, column=1, pady=5)
        self.user_entry.insert(0, "admin")

        tk.Label(form, text="Senha:", bg="#f0f2f5", font=("Arial", 10)).grid(row=1, column=0, sticky="w", pady=5)
        self.pass_entry = tk.Entry(form, width=25, show="*", font=("Arial", 11))
        self.pass_entry.grid(row=1, column=1, pady=5)
        self.pass_entry.insert(0, "123456")

        tk.Button(root, text="Entrar no Sistema", command=self.validar_login, bg="#16a34a", fg="white", font=("Arial", 11, "bold"), width=20, pady=5).pack(pady=20)

    def validar_login(self):
        u, p = self.user_entry.get().strip(), self.pass_entry.get().strip()
        conexao = sqlite3.connect(DB_NAME)
        cursor = conexao.cursor()
        cursor.execute("SELECT cargo FROM usuarios WHERE username = ? AND senha = ?", (u, p))
        res = cursor.fetchone()
        conexao.close()

        if res:
            self.root.destroy()
            main_root = tk.Tk()
            WMSDesktopApp(main_root, u, res[0])
            main_root.mainloop()
        else:
            messagebox.showerror("Erro", "Usuário ou senha inválidos!")


# --- 4. APLICAÇÃO DESKTOP COM MÓDULOS COMPLETOS ---
class WMSDesktopApp:
    def __init__(self, root, usuario, cargo):
        self.root = root
        self.usuario_atual = usuario
        self.cargo_atual = cargo
        
        self.root.title(f"WMS Enterprise - Logado: {usuario} [{cargo}]")
        self.root.geometry("900x650")
        self.root.config(bg="#f0f2f5")

        # Top Bar
        top = tk.Frame(root, bg="#f0f2f5")
        top.pack(fill="x", padx=15, pady=10)
        tk.Label(top, text=f"📦 WMS Core | Operador: {usuario} ({cargo})", font=("Arial", 12, "bold"), bg="#f0f2f5", fg="#1f2937").pack(side="left")
        tk.Button(top, text="Swagger API", command=lambda: webbrowser.open("http://localhost:8000/docs"), bg="#2563eb", fg="white", font=("Arial", 9, "bold"), padx=8, pady=4).pack(side="right")

        # Notebook Abas
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True, padx=15, pady=5)

        self.tab_inbound = ttk.Frame(self.notebook)
        self.tab_estoque = ttk.Frame(self.notebook)
        self.tab_produtos = ttk.Frame(self.notebook)
        self.tab_enderecos = ttk.Frame(self.notebook)
        self.tab_usuarios = ttk.Frame(self.notebook)

        self.notebook.add(self.tab_inbound, text=" 📥 Inbound ")
        self.notebook.add(self.tab_estoque, text=" 📊 Estoque & Excel ")
        self.notebook.add(self.tab_produtos, text=" 🏷️ Produtos ")
        self.notebook.add(self.tab_enderecos, text=" 📍 Endereçamento ")
        self.notebook.add(self.tab_usuarios, text=" 👤 Usuários ")

        self.montar_inbound()
        self.montar_estoque()
        self.montar_produtos()
        self.montar_enderecos()
        self.montar_usuarios()

    def add_input(self, parent, label, row):
        tk.Label(parent, text=label, bg="#f0f2f5", font=("Arial", 9)).grid(row=row, column=0, sticky="w", pady=4)
        e = tk.Entry(parent, width=32, font=("Arial", 10))
        e.grid(row=row, column=1, padx=10, pady=4)
        return e

    # --- ABA 1: INBOUND ---
    def montar_inbound(self):
        f = self.tab_inbound
        tk.Label(f, text="Recebimento de Mercadorias", font=("Arial", 11, "bold"), fg="#333").pack(pady=15)
        form = tk.Frame(f, bg="#f0f2f5", padx=10, pady=10)
        form.pack()

        self.i_sku = self.add_input(form, "SKU:", 0)
        self.i_desc = self.add_input(form, "Descrição:", 1)
        self.i_lote = self.add_input(form, "Lote:", 2)
        self.i_qtd = self.add_input(form, "Quantidade:", 3)
        self.i_end = self.add_input(form, "Endereço:", 4)
        self.i_val = self.add_input(form, "Validade (AAAA-MM-DD):", 5)

        tk.Button(f, text="Registrar Entrada", command=self.salvar_inbound, bg="#16a34a", fg="white", font=("Arial", 10, "bold"), padx=10, pady=6).pack(pady=15)

    def salvar_inbound(self):
        try:
            item = ProdutoRecebimento(
                sku=self.i_sku.get(), descricao=self.i_desc.get(), lote=self.i_lote.get(),
                quantidade=int(self.i_qtd.get()), endereco=self.i_end.get(),
                data_validade=self.i_val.get().strip() or None, usuario=self.usuario_atual
            )
            res = registrar_recebimento(item)
            messagebox.showinfo("Sucesso", f"Estoque alocado: {res['estoque_adicionado']}")
        except Exception as ex:
            messagebox.showerror("Erro", str(ex))

    # --- ABA 2: ESTOQUE & EXPORTAÇÃO EXCEL ---
    def montar_estoque(self):
        f = self.tab_estoque
        tk.Label(f, text="Inventário do Armazém em Tempo Real", font=("Arial", 11, "bold"), fg="#333").pack(pady=10)
        
        btns = tk.Frame(f, bg="#f0f2f5")
        btns.pack(pady=5)
        tk.Button(btns, text="Atualizar Tabela", command=self.carregar_estoque_grid, bg="#2563eb", fg="white", font=("Arial", 9, "bold")).pack(side="left", padx=5)
        tk.Button(btns, text="📥 Extrair para Excel (.xlsx)", command=self.exportar_excel, bg="#16a34a", fg="white", font=("Arial", 9, "bold")).pack(side="left", padx=5)

        self.t_est = ttk.Treeview(f, columns=("SKU", "Desc", "Lote", "Qtd", "End", "Val"), show="headings", height=16)
        for col, nome in [("SKU", "SKU"), ("Desc", "Descrição"), ("Lote", "Lote"), ("Qtd", "Quantidade"), ("End", "Endereço"), ("Val", "Validade")]:
            self.t_est.heading(col, text=nome)
        self.t_est.pack(fill="both", expand=True, padx=10, pady=10)
        self.carregar_estoque_grid()

    def carregar_estoque_grid(self):
        for r in self.t_est.get_children(): self.t_est.delete(r)
        data = consultar_estoque()
        for i in data["itens"]:
            self.t_est.insert("", "end", values=(i["sku"], i["descricao"], i["lote"], i["quantidade"], i["endereco"], i["data_validade"]))

    def exportar_excel(self):
        try:
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Estoque WMS"
            ws.append(["SKU", "Descrição", "Lote", "Quantidade", "Endereço", "Validade"])
            
            data = consultar_estoque()
            for i in data["itens"]:
                ws.append([i["sku"], i["descricao"], i["lote"], i["quantidade"], i["endereco"], i["data_validade"]])
                
            file_path = filedialog.asksaveasfilename(defaultextension=".xlsx", filetypes=[("Excel Files", "*.xlsx")])
            if file_path:
                wb.save(file_path)
                messagebox.showinfo("Sucesso", "Estoque exportado para Excel com sucesso!")
        except Exception as e:
            messagebox.showerror("Erro", f"Erro ao exportar: {str(e)}")

    # --- ABA 3: CADASTRO DE PRODUTOS ---
    def montar_produtos(self):
        f = self.tab_produtos
        tk.Label(f, text="Cadastro Mestre de Produtos (SKU)", font=("Arial", 11, "bold"), fg="#333").pack(pady=10)
        form = tk.Frame(f, bg="#f0f2f5", padx=10, pady=5)
        form.pack()

        self.p_sku = self.add_input(form, "SKU:", 0)
        self.p_desc = self.add_input(form, "Descrição:", 1)
        self.p_cat = self.add_input(form, "Categoria:", 2)
        self.p_peso = self.add_input(form, "Peso Unitário (kg):", 3)

        tk.Button(f, text="Salvar Produto", command=self.salvar_produto, bg="#7c3aed", fg="white", font=("Arial", 9, "bold")).pack(pady=10)

    def salvar_produto(self):
        try:
            conexao = sqlite3.connect(DB_NAME)
            cursor = conexao.cursor()
            cursor.execute("INSERT OR REPLACE INTO produtos_cadastro (sku, descricao, categoria, peso_unitario) VALUES (?, ?, ?, ?)",
                           (self.p_sku.get(), self.p_desc.get(), self.p_cat.get(), float(self.p_peso.get() or 0)))
            conexao.commit()
            conexao.close()
            messagebox.showinfo("Sucesso", "Produto cadastrado com sucesso!")
        except Exception as e:
            messagebox.showerror("Erro", str(e))

    # --- ABA 4: PARÂMETROS DE ENDEREÇAMENTO ---
    def montar_enderecos(self):
        f = self.tab_enderecos
        tk.Label(f, text="Parâmetros de Endereçamento do Armazém", font=("Arial", 11, "bold"), fg="#333").pack(pady=10)
        form = tk.Frame(f, bg="#f0f2f5", padx=10, pady=5)
        form.pack()

        self.e_rua = self.add_input(form, "Rua:", 0)
        self.e_pred = self.add_input(form, "Prédio (Coluna):", 1)
        self.e_niv = self.add_input(form, "Nível (Altura):", 2)
        self.e_ap = self.add_input(form, "Apartamento (Vão):", 3)

        tk.Button(f, text="Cadastrar Endereço Físico", command=self.salvar_endereco, bg="#0284c7", fg="white", font=("Arial", 9, "bold")).pack(pady=10)

    def salvar_endereco(self):
        try:
            conexao = sqlite3.connect(DB_NAME)
            cursor = conexao.cursor()
            cursor.execute("INSERT INTO enderecos_config (rua, predio, nivel, apartamento) VALUES (?, ?, ?, ?)",
                           (self.e_rua.get(), self.e_pred.get(), self.e_niv.get(), self.e_ap.get()))
            conexao.commit()
            conexao.close()
            messagebox.showinfo("Sucesso", "Endereço cadastrado no layout do armazém!")
        except Exception as e:
            messagebox.showerror("Erro", str(e))

    # --- ABA 5: CONTROLE DE USUÁRIOS E PERFIS ---
    def montar_usuarios(self):
        f = self.tab_usuarios
        tk.Label(f, text="Controle de Usuários e Perfis de Acesso", font=("Arial", 11, "bold"), fg="#333").pack(pady=10)
        
        if self.cargo_atual != "Admin":
            tk.Label(f, text="⚠️ Acesso restrito a Administradores.", fg="red", bg="#f0f2f5", font=("Arial", 11)).pack(pady=20)
            return

        form = tk.Frame(f, bg="#f0f2f5", padx=10, pady=5)
        form.pack()

        self.u_name = self.add_input(form, "Novo Usuário:", 0)
        self.u_pass = self.add_input(form, "Senha:", 1)
        
        tk.Label(form, text="Perfil / Cargo:", bg="#f0f2f5", font=("Arial", 9)).grid(row=2, column=0, sticky="w", pady=4)
        self.u_cargo = ttk.Combobox(form, values=["Admin", "Supervisor", "Operador"], width=30, state="readonly")
        self.u_cargo.grid(row=2, column=1, padx=10, pady=4)
        self.u_cargo.set("Operador")

        tk.Button(f, text="Criar Novo Usuário", command=self.cadastrar_usuario, bg="#dc2626", fg="white", font=("Arial", 9, "bold")).pack(pady=10)

    def cadastrar_usuario(self):
        try:
            conexao = sqlite3.connect(DB_NAME)
            cursor = conexao.cursor()
            cursor.execute("INSERT INTO usuarios (username, senha, cargo) VALUES (?, ?, ?)",
                           (self.u_name.get(), self.u_pass.get(), self.u_cargo.get()))
            conexao.commit()
            conexao.close()
            messagebox.showinfo("Sucesso", "Novo usuário cadastrado com sucesso!")
        except Exception as e:
            messagebox.showerror("Erro", f"Usuário já existe ou erro: {str(e)}")


if __name__ == "__main__":
    t = threading.Thread(target=rodar_servidor, daemon=True)
    t.start()

    root = tk.Tk()
    app_login = LoginWindow(root)
    root.mainloop()