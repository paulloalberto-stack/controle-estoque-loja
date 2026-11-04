# Controle de Estoque – © 2026 P.A.S Soluções Tecnológicas. Todos os direitos reservados.
# Servidor local do Controle de Estoque.
# Entrega o sistema em http://127.0.0.1:8787 e grava os dados da loja no banco SQLite dados/loja.sqlite
# (limpar os dados do navegador não apaga mais nada). Só aceita conexões deste computador.
#   pythonw servidor.py --abrir    inicia o servidor (se não estiver rodando) e abre o sistema no Edge
#   pythonw servidor.py --servico  só o servidor (início com o Windows)
#   python  servidor.py --parar    para o servidor (usado pelo instalador)
import os, sys, json, sqlite3, threading, hashlib, base64, re, time, datetime, subprocess, struct, urllib.request, urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

VERSAO_SERVIDOR = '2026.11.04-10'
PORTA = int(os.environ.get('LOJA_PORTA') or 8787)   # outra porta só em testes
ORIGENS_OK = {'http://127.0.0.1:%d' % PORTA, 'http://localhost:%d' % PORTA}
MARCA = 'X-Controle-Estoque'   # cabeçalho que só o próprio sistema manda (outro site não consegue mandar sem permissão)
LIVRES = ('/api/migrar', '/api/status')   # chamados pela página de migração, aberta como arquivo
PROTEGIDAS = ('vendas', 'condicionais', 'trocas', 'entradas', 'movs', 'produtos', 'clientes', 'creditos', 'receber', 'pagar', 'comissoes')
DIAS_AVALIACAO = 30
BASE = os.path.dirname(os.path.abspath(__file__))
ARQ_SISTEMA = os.path.join(BASE, 'Controle_Estoque_Loja.html')
ARQ_MIGRAR = os.path.join(BASE, 'migrar.html')
PASTA_DADOS = os.environ.get('LOJA_DADOS') or os.path.join(BASE, 'dados')
BANCO = os.path.join(PASTA_DADOS, 'loja.sqlite')
PASTA_BACKUP = os.path.join(BASE, 'backups')
PASTA_VERSOES = os.path.join(BASE, 'versoes_anteriores')
ARQ_LOG = os.path.join(PASTA_DADOS, 'servidor.log')
CHAVE_N = int('abc0b4cf8c14c93314410b19a1473dedb981a1cea89088d38cba516d8b3db57dc7f8b8373c4e6c73d0a3f097a186a84e7b5525801888eda126084e1309bf48b766512e45185010f4b37445e1a6f301b63d8865aa9ebc028788d3d4cc151ff21c0c4263613860d86ecf6b61aa4f069ecd003eb30c3b1e193f6a6fbffa218df8f8ed6c3cc26ec5fc6791ece30496913ac65ff912867b6b299318df318de778bd6ccd2b14e56b3ea0c527b3e2dab9730292b68ad128e3bdb4324d76a75ea409be37de88d18dd8a67d4d05e900c64e2be9d26ff0a2b67cbc2c797b59a061d6c485b79b864f2213571d81931bd69d7a1ae09b8b191b48b0ac0b6aa517b86bc8a46c477d15920b5c36ddb6057308b97079a426dcc0d828fbc824068c0d8cae801aa7e089ba23496036875a78fbebc124290d62c1889de5f3126572faba63ddf6a6bdda823f6eb9af1a859853aec84b43ef137c94c667d06f2b952be31d3397fb78e068572104cba3f893bb75c735e626b2cad4af72c96edc2bee5836e4c62e34f48d9d', 16)
LIC_N = int('a9b7adfb44d498f7ebae9fc6c25271af4cb6d5d23ea68b708a484183962ff344641955a3186bb4b4301b079baa33950e6b5d82781ad9731949fd8d7ed2291cb0347f9088045b64be076723b127df0f7470a118a77f55dfd5022729ea989d200c329bafa00c2800c1b62d767e7e933001643efb5f26b19c9c143362ee5febc6505bbad92bca0c4495a6c3fbb3ef4e57a4f05931fa5f0976aeb480644c93680d8dcf72cbb2a9a52b25d66b4682937978117e845368af57670632c86038cb177bab2912a95b284004d74675d2da1028d7aab0f25ff500b0f5231394cbd67b93c0e7544b9be5ef22c6b781613825b63e0ee64470410ebaabe22a50f5c153af39b41d002bfea07cb3186ee888ab327dba6635166a535dbebfd8cb786e0313ba3f5a16b81e9e0abc9ed778426411d43da28633656aea1b29c6ea3c3f102f0085eaa64d38340afd3a75a899cbabd2ac73c1d0df62b6b6e9724e245dbdd698e385982f37c3c48844a0bea4956ec07f36c09af6518515188739c73792952b7347b11f9abd', 16)
LIC_E = int('010001', 16)
CHAVE_E = int('010001', 16)
NL = chr(10)
RESERVADAS = {'meta', 'fotos', 'logs', 'copias', 'colecoes', 'sqlite_sequence', 'apagados'}
NOME_OK = re.compile('^[a-z][A-Za-z0-9_]{0,40}$')
MAX_COPIAS = 20
MANTER_SQLITE = 30


def log(msg):
    try:
        os.makedirs(PASTA_DADOS, exist_ok=True)
        if os.path.exists(ARQ_LOG) and os.path.getsize(ARQ_LOG) > 2000000:
            os.replace(ARQ_LOG, ARQ_LOG + '.1')
        with open(ARQ_LOG, 'a', encoding='utf-8') as f:
            f.write(datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S') + '  ' + msg + NL)
    except Exception:
        pass


def versao_de(texto):
    m = re.search('name="versao-sistema" content="([^"]+)"', texto)
    return m.group(1) if m else ''


# ---------------- banco de dados ----------------
class Banco:
    def __init__(self, caminho):
        os.makedirs(os.path.dirname(caminho), exist_ok=True)
        self.caminho = caminho
        self.trava = threading.RLock()
        self.c = sqlite3.connect(caminho, check_same_thread=False, isolation_level=None)
        self.c.execute('PRAGMA journal_mode=WAL')
        self.c.execute('PRAGMA synchronous=FULL')
        self.c.executescript(
            'CREATE TABLE IF NOT EXISTS meta(chave TEXT PRIMARY KEY, valor TEXT NOT NULL);'
            'CREATE TABLE IF NOT EXISTS colecoes(nome TEXT PRIMARY KEY);'
            'CREATE TABLE IF NOT EXISTS fotos(id TEXT PRIMARY KEY, img TEXT, mini TEXT, quando TEXT);'
            'CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, quando TEXT, usuario TEXT, categoria TEXT, evento TEXT, registro TEXT NOT NULL);'
            'CREATE TABLE IF NOT EXISTS copias(id INTEGER PRIMARY KEY AUTOINCREMENT, quando TEXT, tipo TEXT, usuario TEXT, tamanho INTEGER, produtos INTEGER, vendas INTEGER, dados TEXT NOT NULL);')
        self.cache = {}
        self._migrar()
        ok = self.c.execute('PRAGMA quick_check').fetchone()[0]
        log('banco aberto: ' + caminho + ' (verificação: ' + ok + ')')

    def _cols(self, tabela):
        return [r[1] for r in self.c.execute('PRAGMA table_info("%s")' % tabela)]

    def _migrar(self):
        # versão 2026.11.04-06: cada registro guarda a versão em que mudou e quem gravou (gravação por registro)
        for tab, extras in (('meta', ('ver INTEGER DEFAULT 0', 'por TEXT')), ('colecoes', ('ver INTEGER DEFAULT 0', 'modo TEXT', 'por TEXT'))):
            cs = self._cols(tab)
            for e in extras:
                if e.split()[0] not in cs:
                    self.c.execute('ALTER TABLE %s ADD COLUMN %s' % (tab, e))
        self.c.execute('CREATE TABLE IF NOT EXISTS apagados(colecao TEXT, id TEXT, ver INTEGER, por TEXT)')
        self.c.execute('CREATE INDEX IF NOT EXISTS apagados_ver ON apagados(ver)')
        for nome in self.colecoes():
            self._preparar(nome)

    def _preparar(self, nome):
        self.c.execute('CREATE TABLE IF NOT EXISTS "%s"(pos INTEGER PRIMARY KEY, id TEXT, registro TEXT NOT NULL, ver INTEGER DEFAULT 0, por TEXT)' % nome)
        cs = self._cols(nome)
        for e in ('ver INTEGER DEFAULT 0', 'por TEXT'):
            if e.split()[0] not in cs:
                self.c.execute('ALTER TABLE "%s" ADD COLUMN %s' % (nome, e))
        self.c.execute('CREATE INDEX IF NOT EXISTS "%s__id" ON "%s"(id)' % (nome, nome))
        self.c.execute('CREATE INDEX IF NOT EXISTS "%s__ver" ON "%s"(ver)' % (nome, nome))
        self.c.execute('INSERT OR IGNORE INTO colecoes(nome) VALUES(?)', (nome,))

    def colecoes(self):
        return [r[0] for r in self.c.execute('SELECT nome FROM colecoes')]

    def _lista(self, nome):
        if nome not in self.cache:
            self.cache[nome] = [r[0] for r in self.c.execute('SELECT registro FROM "%s" ORDER BY pos' % nome)]
        return self.cache[nome]

    def vazio(self):
        r = self.c.execute("SELECT valor FROM meta WHERE chave='_salvo'").fetchone()
        return r is None

    def versao(self):
        return int(self.meta_interna('versao') or 0)

    def ler_dados(self):
        with self.trava:
            partes = []
            for chave, valor in self.c.execute("SELECT chave, valor FROM meta WHERE substr(chave, 1, 2) <> '__'"):
                partes.append(json.dumps(chave) + ':' + valor)
            for nome in self.colecoes():
                partes.append(json.dumps(nome) + ':[' + ','.join(self._lista(nome)) + ']')
            return '{' + ','.join(partes) + '}'

    @staticmethod
    def _js(x):
        return json.dumps(x, ensure_ascii=False, separators=(',', ':'))

    @staticmethod
    def _modo(lista):
        ids = [str(x.get('id')) if isinstance(x, dict) and x.get('id') is not None else None for x in lista]
        return 'id' if all(i is not None for i in ids) and len(set(ids)) == len(ids) else 'lista'

    # ---- aplica uma gravação (parcial ou completa) numa transação; devolve a versão nova ----
    def _aplicar(self, por, upserts, apagar, listas, meta_set, meta_del):
        v = self.versao() + 1
        self.meta_interna('versao', v)
        for nome in set(upserts) | set(apagar) | set(listas):
            self._preparar(nome)
            self.cache.pop(nome, None)
        for nome, recs in upserts.items():
            for rec in recs:
                ident, s = str(rec.get('id')), self._js(rec)
                row = self.c.execute('SELECT pos, registro FROM "%s" WHERE id=?' % nome, (ident,)).fetchone()
                if row:
                    if row[1] != s:
                        self.c.execute('UPDATE "%s" SET registro=?, ver=?, por=? WHERE pos=?' % nome, (s, v, por, row[0]))
                else:
                    pos = self.c.execute('SELECT COALESCE(MAX(pos), -1) + 1 FROM "%s"' % nome).fetchone()[0]
                    self.c.execute('INSERT INTO "%s"(pos, id, registro, ver, por) VALUES(?,?,?,?,?)' % nome, (pos, ident, s, v, por))
            self.c.execute("UPDATE colecoes SET ver=?, por=?, modo='id' WHERE nome=?", (v, por, nome))
        for nome, ids in apagar.items():
            for ident in ids:
                if self.c.execute('DELETE FROM "%s" WHERE id=?' % nome, (str(ident),)).rowcount:
                    self.c.execute('INSERT INTO apagados(colecao, id, ver, por) VALUES(?,?,?,?)', (nome, str(ident), v, por))
            self.c.execute('UPDATE colecoes SET ver=?, por=? WHERE nome=?', (v, por, nome))
        for nome, lista in listas.items():
            self.c.execute('DELETE FROM "%s"' % nome)
            for i, x in enumerate(lista):
                ident = x.get('id') if isinstance(x, dict) else None
                self.c.execute('INSERT INTO "%s"(pos, id, registro, ver, por) VALUES(?,?,?,?,?)' % nome, (i, None if ident is None else str(ident), self._js(x), v, por))
            self.c.execute("UPDATE colecoes SET ver=?, por=?, modo='lista' WHERE nome=?", (v, por, nome))
        for k, val in meta_set.items():
            s, atual = self._js(val), self.c.execute('SELECT valor FROM meta WHERE chave=?', (k,)).fetchone()
            if not atual or atual[0] != s:   # valor igual não é regravado (não muda a origem nem a versão)
                self.c.execute('INSERT OR REPLACE INTO meta(chave, valor, ver, por) VALUES(?,?,?,?)', (k, s, v, por))
        for k in meta_del:
            self.c.execute('DELETE FROM meta WHERE chave=?', (k,))
            self.c.execute("INSERT INTO apagados(colecao, id, ver, por) VALUES('__meta',?,?,?)", (k, v, por))
        return v

    def _transacao(self, fn):
        self.c.execute('BEGIN IMMEDIATE')
        try:
            r = fn()
            self.c.execute('COMMIT')
            return r
        except Exception:
            self.c.execute('ROLLBACK')
            self.cache = {}
            raise

    def _diferenca_completa(self, obj):
        """compara os dados inteiros recebidos com o banco e devolve o que mudou (para a gravação completa)"""
        listas_rec = {k: v for k, v in obj.items() if isinstance(v, list) and NOME_OK.match(k) and k not in RESERVADAS}
        upserts, apagar, listas = {}, {}, {}
        modos = {n: m for n, m in self.c.execute('SELECT nome, modo FROM colecoes')}
        for nome, lista in listas_rec.items():
            if self._modo(lista) == 'id' and modos.get(nome, 'id') != 'lista':
                atuais = {r[0]: r[1] for r in self.c.execute('SELECT id, registro FROM "%s"' % nome)} if nome in modos else {}
                novos = {str(x['id']): x for x in lista}
                up = [x for k, x in novos.items() if atuais.get(k) != self._js(x)]
                ap = [k for k in atuais if k not in novos]
                if up or nome not in modos:
                    upserts[nome] = up
                if ap:
                    apagar[nome] = ap
            elif nome not in modos or [self._js(x) for x in lista] != self._lista(nome):
                listas[nome] = lista
        for nome in set(modos) - set(listas_rec):
            listas[nome] = []
        atuais_meta = {k: s for k, s in self.c.execute("SELECT chave, valor FROM meta WHERE substr(chave, 1, 2) <> '__'")}
        outros = {k: v for k, v in obj.items() if k not in listas_rec}
        meta_set = {k: v for k, v in outros.items() if atuais_meta.get(k) != self._js(v)}
        meta_del = [k for k in atuais_meta if k not in outros]
        return upserts, apagar, listas, meta_set, meta_del

    def gravar_dados(self, obj, forcar=False, por='completo'):
        if not isinstance(obj, dict) or not isinstance(obj.get('usuarios'), list) or not isinstance(obj.get('produtos'), list):
            raise ValueError('dados inválidos')
        with self.trava:
            atual = self.c.execute("SELECT valor FROM meta WHERE chave='_salvo'").fetchone()
            if atual and not forcar and float(json.loads(atual[0]) or 0) > float(obj.get('_salvo') or 0):
                return False
            self._transacao(lambda: self._aplicar(por, *self._diferenca_completa(obj)))
            return True

    def conflitos(self, base, por, upserts, apagar, listas, meta_set):
        """registros que outra janela/computador mudou depois da versão 'base' e que esta gravação também muda"""
        out = []
        existentes = set(self.colecoes())
        for nome, recs in upserts.items():
            if nome not in existentes:
                continue
            for rec in recs:
                row = self.c.execute('SELECT registro, ver, por FROM "%s" WHERE id=?' % nome, (str(rec.get('id')),)).fetchone()
                if row and row[1] > base and (row[2] or '') != por and row[0] != self._js(rec):
                    out.append(nome + ' ' + str(rec.get('id')))
        for nome, ids in apagar.items():
            if nome in existentes:
                for ident in ids:
                    row = self.c.execute('SELECT ver, por FROM "%s" WHERE id=?' % nome, (str(ident),)).fetchone()
                    if row and row[0] > base and (row[1] or '') != por:
                        out.append(nome + ' ' + str(ident))
        for nome, lista in listas.items():
            row = self.c.execute('SELECT ver, por FROM colecoes WHERE nome=?', (nome,)).fetchone()
            if row and (row[0] or 0) > base and (row[1] or '') != por and [self._js(x) for x in lista] != self._lista(nome):
                out.append(nome)
        for k, val in meta_set.items():
            if k == '_salvo':
                continue
            row = self.c.execute('SELECT valor, ver, por FROM meta WHERE chave=?', (k,)).fetchone()
            if row and (row[1] or 0) > base and (row[2] or '') != por and row[0] != self._js(val):
                out.append(k)
        return out

    def gravar_parcial(self, base, por, upserts, apagar, listas, meta_set, meta_del, forcar=False):
        with self.trava:
            def fazer():
                c = [] if forcar else self.conflitos(base, por, upserts, apagar, listas, meta_set)
                if c:
                    return {'conflitos': c}
                return {'versao': self._aplicar(por, upserts, apagar, listas, meta_set, meta_del)}
            return self._transacao(fazer)

    def mudancas(self, desde, por):
        """o que outras janelas/computadores gravaram depois da versão 'desde' (em texto JSON, sem reconverter)"""
        with self.trava:
            partes_c, partes_l = [], []
            for nome, modo, ver, quem in self.c.execute('SELECT nome, modo, ver, por FROM colecoes').fetchall():
                if modo == 'lista':
                    if (ver or 0) > desde and (quem or '') != por:
                        partes_l.append(json.dumps(nome) + ':[' + ','.join(self._lista(nome)) + ']')
                else:
                    regs = [r[0] for r in self.c.execute("""SELECT registro FROM "%s" WHERE ver > ? AND COALESCE(por, '') <> ? ORDER BY pos""" % nome, (desde, por))]
                    if regs:
                        partes_c.append(json.dumps(nome) + ':[' + ','.join(regs) + ']')
            ap = {}
            for nome, ident in self.c.execute("SELECT colecao, id FROM apagados WHERE ver > ? AND COALESCE(por, '') <> ?", (desde, por)):
                ap.setdefault(nome, []).append(ident)
            meta = [json.dumps(k) + ':' + s for k, s in self.c.execute("SELECT chave, valor FROM meta WHERE ver > ? AND COALESCE(por, '') <> ? AND substr(chave, 1, 2) <> '__'", (desde, por))]
            return '{"versao":%d,"colecoes":{%s},"listas":{%s},"apagados":%s,"meta":{%s}}' % (self.versao(), ','.join(partes_c), ','.join(partes_l), json.dumps(ap, ensure_ascii=False), ','.join(meta))

    def config(self):
        with self.trava:
            r = self.c.execute("SELECT valor FROM meta WHERE chave='config'").fetchone()
            return json.loads(r[0]) if r else {}

    def mudou_protegido(self, obj):
        with self.trava:
            existentes = set(self.colecoes())
            for nome in PROTEGIDAS:
                novas = [json.dumps(x, ensure_ascii=False, separators=(',', ':')) for x in (obj.get(nome) or [])]
                if novas != (self._lista(nome) if nome in existentes else []):
                    return nome
            return None

    def meta_interna(self, chave, valor=None):
        with self.trava:
            if valor is None:
                r = self.c.execute('SELECT valor FROM meta WHERE chave=?', ('__' + chave,)).fetchone()
                return json.loads(r[0]) if r else None
            self.c.execute('INSERT OR REPLACE INTO meta(chave, valor) VALUES(?,?)', ('__' + chave, json.dumps(valor, ensure_ascii=False)))

    # fotos
    def fotos(self, so_minis=False):
        with self.trava:
            if so_minis:
                return {i: m for i, m in self.c.execute('SELECT id, mini FROM fotos')}
            return {i: {'img': a, 'mini': m} for i, a, m in self.c.execute('SELECT id, img, mini FROM fotos')}

    def foto(self, ident):
        with self.trava:
            r = self.c.execute('SELECT img, mini FROM fotos WHERE id=?', (ident,)).fetchone()
            return {'img': r[0], 'mini': r[1]} if r else None

    def gravar_fotos(self, fotos):
        with self.trava:
            self.c.execute('BEGIN IMMEDIATE')
            try:
                for ident, f in fotos.items():
                    if f and f.get('img'):
                        self.c.execute('INSERT OR REPLACE INTO fotos(id, img, mini, quando) VALUES(?,?,?,?)', (ident, f['img'], f.get('mini') or f['img'], agora()))
                self.c.execute('COMMIT')
            except Exception:
                self.c.execute('ROLLBACK')
                raise

    def limpar_fotos(self, usadas):
        with self.trava:
            ids = [r[0] for r in self.c.execute('SELECT id FROM fotos')]
            sobra = [i for i in ids if i not in set(usadas)]
            for i in sobra:
                self.c.execute('DELETE FROM fotos WHERE id=?', (i,))
            return sobra

    # logs
    def logs(self):
        with self.trava:
            out = []
            for ident, reg in self.c.execute('SELECT id, registro FROM logs ORDER BY id'):
                r = json.loads(reg)
                r['id'] = ident
                out.append(r)
            return out

    def gravar_logs(self, lista, sem_repetir=False):
        with self.trava:
            vistos = set()
            if sem_repetir:
                for reg, in self.c.execute('SELECT registro FROM logs'):
                    r = json.loads(reg)
                    vistos.add('%s|%s|%s' % (r.get('ts'), r.get('ev'), r.get('u')))
            self.c.execute('BEGIN IMMEDIATE')
            try:
                n = 0
                for r in lista:
                    if not isinstance(r, dict):
                        continue
                    r = dict(r)
                    r.pop('id', None)
                    chave = '%s|%s|%s' % (r.get('ts'), r.get('ev'), r.get('u'))
                    if sem_repetir and chave in vistos:
                        continue
                    vistos.add(chave)
                    self.c.execute('INSERT INTO logs(ts, quando, usuario, categoria, evento, registro) VALUES(?,?,?,?,?,?)',
                                   (r.get('ts'), r.get('q'), r.get('u'), r.get('cat'), r.get('ev'), json.dumps(r, ensure_ascii=False)))
                    n += 1
                self.c.execute('COMMIT')
                return n
            except Exception:
                self.c.execute('ROLLBACK')
                raise

    # cópias internas (as 20 últimas)
    def copias(self):
        with self.trava:
            cols = ['id', 'quando', 'tipo', 'usuario', 'tamanho', 'produtos', 'vendas', 'dados']
            return [dict(zip(cols, r)) for r in self.c.execute('SELECT ' + ','.join(cols) + ' FROM copias ORDER BY id')]

    def gravar_copia(self, c):
        with self.trava:
            self.c.execute('INSERT INTO copias(quando, tipo, usuario, tamanho, produtos, vendas, dados) VALUES(?,?,?,?,?,?,?)',
                           (c.get('quando'), c.get('tipo'), c.get('usuario'), c.get('tamanho'), c.get('produtos'), c.get('vendas'), c.get('dados') or ''))
            self.c.execute('DELETE FROM copias WHERE id NOT IN (SELECT id FROM copias ORDER BY id DESC LIMIT ?)', (MAX_COPIAS,))

    def tamanho(self):
        t = 0
        for suf in ('', '-wal'):
            try:
                t += os.path.getsize(self.caminho + suf)
            except OSError:
                pass
        return t

    def copiar_para(self, destino):
        with self.trava:
            d = sqlite3.connect(destino)
            try:
                self.c.backup(d)
            finally:
                d.close()


def agora():
    return datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S')


# ---------------- assinatura digital (RSA PKCS#1 v1.5 com SHA-256) ----------------
def rsa_valida(n, e, mensagem, assinatura):
    try:
        k = (n.bit_length() + 7) // 8
        em = pow(int.from_bytes(assinatura, 'big'), e, n).to_bytes(k, 'big')
        info = bytes.fromhex('3031300d060960864801650304020105000420') + hashlib.sha256(mensagem).digest()
        return em == bytes([0, 1]) + bytes([255]) * (k - 3 - len(info)) + bytes([0]) + info
    except Exception:
        return False


def assinatura_valida(versao, sha, ass_b64, prefixo='lojaRoupas'):
    try:
        return rsa_valida(CHAVE_N, CHAVE_E, (prefixo + '|' + versao + '|' + sha).encode('utf-8'), base64.b64decode(ass_b64))
    except Exception:
        return False


# ---------------- licença (conferida também aqui, com data protegida contra relógio atrasado) ----------------
def b64u(s):
    return base64.urlsafe_b64decode(s + '=' * (-len(s) % 4))


def ler_licenca(codigo):
    m = re.match('^PAS1-([A-Za-z0-9_-]+)[.]([A-Za-z0-9_-]+)$', re.sub('[^A-Za-z0-9_.-]', '', codigo or ''))
    if not m:
        return None
    try:
        dados, ass = b64u(m.group(1)), b64u(m.group(2))
        return json.loads(dados.decode('utf-8')) if rsa_valida(LIC_N, LIC_E, dados, ass) else None
    except Exception:
        return None


def hoje_seguro(b):
    h = datetime.date.today().isoformat()
    m = b.meta_interna('dataMax') or h
    if h > m:
        b.meta_interna('dataMax', h)
        m = h
    return m, h < m


def situacao_licenca(b, config):
    hoje, atrasado = hoje_seguro(b)
    ini = b.meta_interna('licencaInicio')
    if not ini:
        ini = hoje
        b.meta_interna('licencaInicio', ini)
    config = config or {}
    l = ler_licenca(config.get('licenca'))
    sit = {'hoje': hoje, 'inicio': ini, 'relogioAtrasado': atrasado}
    if l and re.sub('[^0-9]', '', str(l.get('cnpj'))) == re.sub('[^0-9]', '', str(config.get('cnpj') or '')):
        fim = (datetime.date.fromisoformat(l['validade']) + datetime.timedelta(days=int(l.get('tolerancia') or 0))).isoformat()
        sit.update(sit='ok' if hoje <= fim else 'bloqueada', validade=l['validade'], fim=fim)
    else:
        fim = (datetime.date.fromisoformat(ini) + datetime.timedelta(days=DIAS_AVALIACAO)).isoformat()
        sit.update(sit='avaliacao' if hoje <= fim else 'bloqueada', fim=fim)
    return sit


def instalar_versao(conteudo, versao, sha, ass):
    sha_real = hashlib.sha256(conteudo).hexdigest()
    if sha_real != (sha or '').lower():
        raise ValueError('o arquivo recebido não confere com o código SHA-256 publicado')
    if not assinatura_valida(versao, sha_real, ass):
        raise ValueError('ASSINATURA INVÁLIDA: esta versão não foi publicada pela loja e foi recusada')
    texto = conteudo.decode('utf-8')
    if versao_de(texto) != versao:
        raise ValueError('o número da versão dentro do arquivo não confere')
    atual = open(ARQ_SISTEMA, encoding='utf-8').read() if os.path.exists(ARQ_SISTEMA) else ''
    v_atual = versao_de(atual)
    if v_atual and not versao > v_atual:
        raise ValueError('a versão %s não é mais nova que a instalada (%s)' % (versao, v_atual))
    os.makedirs(PASTA_VERSOES, exist_ok=True)
    if atual:
        nome = 'Controle_Estoque_Loja_%s_%s.html' % (v_atual or 'sem_numero', datetime.datetime.now().strftime('%Y-%m-%d_%H%M'))
        with open(os.path.join(PASTA_VERSOES, nome), 'w', encoding='utf-8', newline='') as f:
            f.write(atual)
        antigos = sorted((os.path.join(PASTA_VERSOES, n) for n in os.listdir(PASTA_VERSOES) if n.endswith('.html')), key=os.path.getmtime)
        for a in antigos[:-10]:
            os.remove(a)
    tmp = ARQ_SISTEMA + '.novo'
    with open(tmp, 'wb') as f:
        f.write(conteudo)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, ARQ_SISTEMA)
    if hashlib.sha256(open(ARQ_SISTEMA, 'rb').read()).hexdigest() != sha_real:
        raise ValueError('a cópia gravada não ficou igual ao arquivo conferido; use VOLTAR_VERSAO_ANTERIOR')
    log('ATUALIZADO: %s -> %s' % (v_atual, versao))
    return v_atual


def instalar_servidor(conteudo, versao, sha, ass):
    sha_real = hashlib.sha256(conteudo).hexdigest()
    if sha_real != (sha or '').lower():
        raise ValueError('o servidor recebido não confere com o código SHA-256 publicado')
    if not assinatura_valida(versao, sha_real, ass, 'lojaRoupasServidor'):
        raise ValueError('ASSINATURA INVÁLIDA: este servidor não foi publicado pela P.A.S e foi recusado')
    texto = conteudo.decode('utf-8')
    if ("VERSAO_SERVIDOR = '" + versao + "'") not in texto:
        raise ValueError('o número da versão dentro do servidor não confere')
    if not versao > VERSAO_SERVIDOR:
        raise ValueError('o servidor %s não é mais novo que o instalado (%s)' % (versao, VERSAO_SERVIDOR))
    compile(texto, 'servidor.py', 'exec')
    os.makedirs(PASTA_VERSOES, exist_ok=True)
    atual = os.path.abspath(__file__)
    with open(atual, 'rb') as f:
        antigo = f.read()
    with open(os.path.join(PASTA_VERSOES, 'servidor_%s.py' % VERSAO_SERVIDOR), 'wb') as f:
        f.write(antigo)
    with open(atual + '.novo', 'wb') as f:
        f.write(conteudo)
        f.flush()
        os.fsync(f.fileno())
    os.replace(atual + '.novo', atual)
    log('SERVIDOR ATUALIZADO: %s -> %s (reiniciando)' % (VERSAO_SERVIDOR, versao))


def reiniciar():
    time.sleep(0.5)
    exe = sys.executable
    if os.path.basename(exe).lower() == 'python.exe' and os.path.exists(os.path.join(os.path.dirname(exe), 'pythonw.exe')):
        exe = os.path.join(os.path.dirname(exe), 'pythonw.exe')
    subprocess.Popen([exe, os.path.abspath(__file__), '--servico', '--esperar'], cwd=BASE, creationflags=0x00000008 | 0x00000200, close_fds=True)
    SERVIDOR_HTTP.shutdown()


# ---------------- cópia diária do banco ----------------
def copia_diaria(banco):
    try:
        os.makedirs(PASTA_BACKUP, exist_ok=True)
        hoje = datetime.date.today().isoformat()
        destino = os.path.join(PASTA_BACKUP, 'loja_' + hoje + '.sqlite')
        if not os.path.exists(destino) and not banco.vazio():
            banco.copiar_para(destino + '.tmp')
            os.replace(destino + '.tmp', destino)
            log('cópia diária do banco: ' + destino)
        copias = sorted(n for n in os.listdir(PASTA_BACKUP) if n.startswith('loja_') and n.endswith('.sqlite'))
        for n in copias[:-MANTER_SQLITE]:
            os.remove(os.path.join(PASTA_BACKUP, n))
        extra = banco.meta_interna('pastaExtra')
        if extra and os.path.isdir(extra) and os.path.exists(destino):
            alvo = os.path.join(extra, os.path.basename(destino))
            if not os.path.exists(alvo):
                banco.copiar_para(alvo)
                log('cópia diária também em: ' + alvo)
    except Exception as e:
        log('falha na cópia diária: %r' % e)


def laco_copias(banco):
    while True:
        copia_diaria(banco)
        time.sleep(1800)


def gravar_arquivo_backup(nome, conteudo, manter, pasta_extra):
    if not re.match('^backup_loja_[0-9A-Za-z_.-]+[.]json$', nome or ''):
        raise ValueError('nome de arquivo inválido')
    onde = []
    destinos = [os.path.join(PASTA_BACKUP, 'arquivos')]
    if pasta_extra:
        if not os.path.isdir(pasta_extra):
            raise ValueError('a pasta extra "%s" não existe ou não está acessível (pen drive desconectado?)' % pasta_extra)
        destinos.append(pasta_extra)
    for d in destinos:
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, nome), 'w', encoding='utf-8', newline='') as f:
            f.write(conteudo)
        onde.append(d)
        nomes = sorted(n for n in os.listdir(d) if n.startswith('backup_loja_') and n.endswith('.json'))
        for n in nomes[:-max(1, int(manter or 30))]:
            os.remove(os.path.join(d, n))
    return onde


# ---------------- ícone da loja e atalhos da área de trabalho ----------------
PNG_ASSINATURA = bytes([137, 80, 78, 71, 13, 10, 26, 10])
PS_ATALHOS = """$ws = New-Object -ComObject WScript.Shell
$ico = $env:LOJA_ICO; $criar = $env:LOJA_CRIAR -eq '1'; $feitos = @()
$pastas = @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))
if ($env:LOJA_PASTAS_ATALHO) { $pastas = $env:LOJA_PASTAS_ATALHO.Split(';') }   # usado nos testes
foreach ($p in $pastas) {
  if (-not $p) { continue }
  New-Item -ItemType Directory -Force -Path $p | Out-Null
  $f = Join-Path $p 'Controle de Estoque.lnk'
  if (-not (Test-Path $f) -and -not $criar) { continue }
  $l = $ws.CreateShortcut($f)
  if ($criar -or ($l.Arguments -like '*servidor.py*')) {
    $l.TargetPath = $env:LOJA_PYW; $l.Arguments = '"' + $env:LOJA_SRV + '" --abrir'; $l.WorkingDirectory = $env:LOJA_BASE
    $l.Description = 'Controle de Estoque da loja'
    if ($ico -and (Test-Path $ico)) { $l.IconLocation = $ico + ',0' }
    $l.Save(); $feitos += $f
  }
}
try { Start-Process ie4uinit.exe -ArgumentList '-show' -WindowStyle Hidden } catch { }
$feitos -join '|'
"""


def icone_atual():
    nomes = sorted(n for n in os.listdir(BASE) if n.startswith('loja_') and n.endswith('.ico'))
    return os.path.join(BASE, nomes[-1]) if nomes else ''


def montar_ico(pngs):
    cab = struct.pack('<HHH', 0, 1, len(pngs))
    entradas, dados, pos = b'', b'', 6 + 16 * len(pngs)
    for png in pngs:
        if png[:8] != PNG_ASSINATURA:
            raise ValueError('imagem do ícone inválida')
        w, h = struct.unpack('>II', png[16:24])
        entradas += struct.pack('<BBBBHHII', w if w < 256 else 0, h if h < 256 else 0, 0, 0, 1, 32, len(png), pos)
        dados += png
        pos += len(png)
    return cab + entradas + dados


def atualizar_atalhos(criar=False):
    pyw = os.path.join(os.path.dirname(sys.executable), 'pythonw.exe')
    env = dict(os.environ, LOJA_ICO=icone_atual(), LOJA_PYW=pyw, LOJA_SRV=os.path.join(BASE, 'servidor.py'), LOJA_BASE=BASE, LOJA_CRIAR='1' if criar else '0')
    cod = base64.b64encode(PS_ATALHOS.encode('utf-16-le')).decode('ascii')
    r = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-EncodedCommand', cod], capture_output=True, text=True, env=env, timeout=60, creationflags=0x08000000)
    if r.returncode != 0:
        raise ValueError('não foi possível mexer no atalho: ' + (r.stderr or '').strip()[:300])
    feitos = [x for x in (r.stdout or '').strip().split('|') if x]
    log('atalhos atualizados: ' + (', '.join(feitos) or 'nenhum'))
    return feitos


def gravar_icone(hash_, pngs_b64):
    pngs = [base64.b64decode(x) for x in pngs_b64]
    ico = montar_ico(pngs)
    nome = os.path.join(BASE, 'loja_' + re.sub('[^0-9a-f]', '', (hash_ or '')[:12]) + '.ico')
    with open(nome + '.tmp', 'wb') as f:
        f.write(ico)
    os.replace(nome + '.tmp', nome)
    for n in os.listdir(BASE):   # nome novo a cada logo: o Windows não reaproveita o ícone antigo guardado
        if n.startswith('loja_') and n.endswith('.ico') and os.path.join(BASE, n) != nome:
            os.remove(os.path.join(BASE, n))
    BANCO_ATIVO.meta_interna('iconeHash', hash_)
    return nome


# ---------------- HTTP ----------------
BANCO_ATIVO = None
SERVIDOR_HTTP = None


class Atendente(BaseHTTPRequestHandler):
    server_version = 'ControleEstoque/' + VERSAO_SERVIDOR
    protocol_version = 'HTTP/1.1'

    def log_message(self, *a):
        pass

    def _host_ok(self):
        h = (self.headers.get('Host') or '').lower()
        return h in ('127.0.0.1:%d' % PORTA, 'localhost:%d' % PORTA)

    def _cors(self):
        # só a página de migração (aberta como arquivo) chama de fora
        if self.path.split('?')[0] in LIVRES and self.headers.get('Origin') == 'null':
            self.send_header('Access-Control-Allow-Origin', 'null')
            self.send_header('Access-Control-Allow-Headers', 'Content-Type, ' + MARCA)
            self.send_header('Access-Control-Allow-Methods', 'GET, POST')

    def _barrar(self):
        # recusa pedidos de outros sites abertos no navegador (eles podiam gravar ou apagar dados)
        if not self._host_ok():
            return 'acesso negado'
        caminho = self.path.split('?')[0]
        if not caminho.startswith('/api/'):
            return None
        origem, site = self.headers.get('Origin'), (self.headers.get('Sec-Fetch-Site') or '').lower()
        livre = caminho in LIVRES
        if origem is not None and origem not in ORIGENS_OK and not (origem == 'null' and livre):
            return 'pedido de outro site recusado'
        if site in ('cross-site', 'same-site') and not livre:
            return 'pedido de outro site recusado'
        if self.command in ('POST', 'PUT') and (origem is not None or site) and self.headers.get(MARCA) != '1':
            return 'pedido sem a marca do sistema recusado'
        if caminho == '/api/parar' and (origem is not None or site):
            return 'só o instalador pode parar o servidor'
        return None

    def _recusar(self, motivo):
        log('RECUSADO %s %s (origem %s): %s' % (self.command, self.path.split('?')[0], self.headers.get('Origin'), motivo))
        return self._erro(403, motivo)

    def _enviar(self, codigo, corpo, tipo='application/json; charset=utf-8'):
        if isinstance(corpo, str):
            corpo = corpo.encode('utf-8')
        self.send_response(codigo)
        self.send_header('Content-Type', tipo)
        self.send_header('Content-Length', str(len(corpo)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')   # não deixa outro site abrir o sistema escondido dentro dele
        self.send_header('Content-Security-Policy', "frame-ancestors 'none'")
        self.send_header('Referrer-Policy', 'no-referrer')
        self._cors()
        self.end_headers()
        self.wfile.write(corpo)

    def _json(self, codigo, obj):
        self._enviar(codigo, json.dumps(obj, ensure_ascii=False))

    def _erro(self, codigo, msg):
        self._json(codigo, {'erro': msg})

    def _corpo(self):
        n = int(self.headers.get('Content-Length') or 0)
        if n > 300 * 1024 * 1024:
            raise ValueError('envio grande demais')
        return self.rfile.read(n) if n else b''

    def do_OPTIONS(self):
        if not self._host_ok() or not (self.path.split('?')[0] in LIVRES and self.headers.get('Origin') == 'null'):
            return self._erro(403, 'acesso negado')
        self.send_response(204)
        self._cors()
        self.send_header('Content-Length', '0')
        self.end_headers()

    def do_GET(self):
        motivo = self._barrar()
        if motivo:
            return self._recusar(motivo)
        b = BANCO_ATIVO
        caminho = self.path.split('?')[0]
        try:
            if caminho in ('/', '/index.html', '/Controle_Estoque_Loja.html'):
                with open(ARQ_SISTEMA, 'rb') as f:
                    return self._enviar(200, f.read(), 'text/html; charset=utf-8')
            if caminho == '/api/status':
                return self._json(200, {'app': 'lojaRoupas', 'servidor': VERSAO_SERVIDOR, 'sistema': versao_de(open(ARQ_SISTEMA, encoding='utf-8').read()) if os.path.exists(ARQ_SISTEMA) else '',
                                        'vazio': b.vazio(), 'migradoEm': b.meta_interna('migradoEm'), 'banco': b.caminho, 'tamanho': b.tamanho(),
                                        'pasta': BASE, 'backups': PASTA_BACKUP, 'pastaExtra': b.meta_interna('pastaExtra') or '', 'iconeHash': b.meta_interna('iconeHash') or '', 'icone': icone_atual(), 'licenca': situacao_licenca(b, b.config()), 'rede': info_rede()})
            if caminho == '/api/dados':
                corpo = b.ler_dados() if not b.vazio() else '{}'
                if 'versao=1' in self.path:   # sistema novo: dados + versão (gravação por registro)
                    return self._enviar(200, '{"versao":%d,"dados":%s}' % (b.versao(), corpo))
                return self._enviar(200, corpo)
            if caminho == '/api/mudancas':
                q = urllib.parse.parse_qs(self.path.split('?', 1)[1] if '?' in self.path else '')
                return self._enviar(200, b.mudancas(int((q.get('desde') or ['0'])[0] or 0), (q.get('cliente') or [''])[0]))
            if caminho == '/api/fotos':
                return self._json(200, b.fotos('minis=1' in self.path))
            if caminho.startswith('/api/fotos/'):
                f = b.foto(urllib.parse.unquote(caminho[11:]))
                return self._json(200, f) if f else self._erro(404, 'foto não encontrada')
            if caminho == '/api/logs':
                return self._json(200, b.logs())
            if caminho == '/api/copias':
                return self._json(200, b.copias())
            return self._erro(404, 'não encontrado')
        except Exception as e:
            log('erro GET %s: %r' % (caminho, e))
            return self._erro(500, str(e))

    def do_PUT(self):
        return self.do_POST()

    def do_POST(self):
        motivo = self._barrar()
        if motivo:
            return self._recusar(motivo)
        b = BANCO_ATIVO
        caminho = self.path.split('?')[0]
        try:
            corpo = self._corpo()
            if caminho == '/api/instalarServidor':
                h = self.headers
                instalar_servidor(corpo, h.get('X-Versao') or '', h.get('X-Sha256') or '', h.get('X-Assinatura') or '')
                self._json(200, {'ok': True, 'de': VERSAO_SERVIDOR})
                threading.Thread(target=reiniciar, daemon=True).start()
                return None
            if caminho == '/api/instalar':
                h = self.headers
                de = instalar_versao(corpo, h.get('X-Versao') or '', h.get('X-Sha256') or '', h.get('X-Assinatura') or '')
                return self._json(200, {'ok': True, 'de': de})
            dados = json.loads(corpo.decode('utf-8') or 'null')
            if caminho == '/api/gravar':
                ups = {k: v.get('upsert') or [] for k, v in (dados.get('colecoes') or {}).items()}
                aps = {k: v.get('apagar') or [] for k, v in (dados.get('colecoes') or {}).items() if v.get('apagar')}
                lis = dados.get('listas') or {}
                mset, mdel = (dados.get('meta') or {}).get('set') or {}, (dados.get('meta') or {}).get('del') or []
                mset = {k: v for k, v in mset.items() if not str(k).startswith('__')}
                mdel = [k for k in mdel if not str(k).startswith('__')]
                for nome in list(ups) + list(lis):
                    if not NOME_OK.match(nome) or nome in RESERVADAS:
                        return self._erro(400, 'coleção inválida: ' + nome)
                if any(not isinstance(r, dict) or r.get('id') is None for l in ups.values() for r in l):
                    return self._erro(400, 'registro sem id')
                cfg = mset.get('config') if isinstance(mset.get('config'), dict) else b.config()
                if situacao_licenca(b, cfg)['sit'] == 'bloqueada':
                    mexe = [n for n in PROTEGIDAS if ups.get(n) or aps.get(n) or n in lis]
                    if mexe:
                        log('RECUSADO pela licença: alteração em %s com a licença vencida' % mexe[0])
                        return self._erro(423, 'licença vencida: o sistema está em modo consulta e não registra vendas nem movimentações')
                r = b.gravar_parcial(int(dados.get('base') or 0), str(dados.get('cliente') or '')[:40], ups, aps, lis, mset, mdel, forcar='forcar=1' in self.path)
                if 'conflitos' in r:
                    log('conflito de gravação (outra janela/computador): ' + ', '.join(r['conflitos'][:10]))
                    return self._json(409, {'erro': 'outra janela ou outro computador alterou os mesmos dados ao mesmo tempo', 'conflitos': r['conflitos'][:50]})
                if not os.path.exists(os.path.join(PASTA_BACKUP, 'loja_' + datetime.date.today().isoformat() + '.sqlite')):
                    threading.Thread(target=copia_diaria, args=(b,), daemon=True).start()
                return self._json(200, {'ok': True, 'versao': r['versao']})
            if caminho == '/api/dados':
                if isinstance(dados, dict) and situacao_licenca(b, dados.get('config'))['sit'] == 'bloqueada':
                    mudou = b.mudou_protegido(dados)
                    if mudou:
                        log('RECUSADO pela licença: alteração em %s com a licença vencida' % mudou)
                        return self._erro(423, 'licença vencida: o sistema está em modo consulta e não registra vendas nem movimentações')
                if not b.gravar_dados(dados, forcar='forcar=1' in self.path):
                    return self._erro(409, 'outra janela gravou dados mais novos; recarregue o sistema (F5)')
                if not os.path.exists(os.path.join(PASTA_BACKUP, 'loja_' + datetime.date.today().isoformat() + '.sqlite')):
                    threading.Thread(target=copia_diaria, args=(b,), daemon=True).start()   # 1ª gravação do dia
                return self._json(200, {'ok': True})
            if caminho.startswith('/api/fotos/') and caminho not in ('/api/fotos/lote', '/api/fotos/limpar'):
                b.gravar_fotos({urllib.parse.unquote(caminho[11:]): dados})
                return self._json(200, {'ok': True})
            if caminho == '/api/fotos/lote':
                b.gravar_fotos(dados or {})
                return self._json(200, {'ok': True})
            if caminho == '/api/fotos/limpar':
                return self._json(200, {'removidas': b.limpar_fotos(dados.get('usadas') or [])})
            if caminho == '/api/logs':
                return self._json(200, {'gravados': b.gravar_logs(dados or [])})
            if caminho == '/api/logs/restaurar':
                return self._json(200, {'gravados': b.gravar_logs(dados or [], sem_repetir=True)})
            if caminho == '/api/copias':
                b.gravar_copia(dados or {})
                return self._json(200, {'ok': True})
            if caminho == '/api/backup':
                onde = gravar_arquivo_backup(dados.get('nome'), dados.get('conteudo') or '', dados.get('manter'), dados.get('pasta') or '')
                return self._json(200, {'ok': True, 'onde': onde})
            if caminho == '/api/pastaExtra':
                p = (dados.get('pasta') or '').strip()
                if p and not os.path.isdir(p):
                    return self._erro(400, 'a pasta "%s" não existe ou não está acessível' % p)
                b.meta_interna('pastaExtra', p)
                if p:
                    threading.Thread(target=copia_diaria, args=(b,), daemon=True).start()
                return self._json(200, {'ok': True})
            if caminho == '/api/rede':
                if isinstance(self, AtendenteRede):
                    return self._erro(403, 'só no computador do caixa')
                ligar = bool(dados.get('ativo'))
                b.meta_interna('rede', ligar)
                ok = iniciar_rede() if ligar else (parar_rede() or True)
                log('venda pelo celular %s pelo sistema' % ('liberada' if ligar else 'bloqueada'))
                return self._json(200 if ok else 500, dict(info_rede(), erro=REDE['erro']))
            if caminho == '/api/icone':
                nome = gravar_icone(dados.get('hash'), dados.get('pngs') or [])
                return self._json(200, {'ok': True, 'icone': nome, 'atalhos': atualizar_atalhos(False)})
            if caminho == '/api/atalho':
                return self._json(200, {'ok': True, 'atalhos': atualizar_atalhos(True)})
            if caminho == '/api/migrar':
                if not b.vazio():
                    return self._erro(409, 'o banco já tem dados; nada foi migrado')
                if not b.gravar_dados(dados.get('dados'), forcar=True):
                    return self._erro(500, 'não gravou')
                b.gravar_fotos(dados.get('fotos') or {})
                b.gravar_logs(dados.get('logs') or [])
                for c in dados.get('copias') or []:
                    b.gravar_copia(c)
                b.meta_interna('migradoEm', agora())
                lido = json.loads(b.ler_dados())
                log('dados migrados do navegador: %d produtos, %d vendas, %d fotos, %d logs' % (len(lido.get('produtos', [])), len(lido.get('vendas', [])), len(dados.get('fotos') or {}), len(dados.get('logs') or [])))
                return self._json(200, {'ok': True, 'produtos': len(lido.get('produtos', [])), 'vendas': len(lido.get('vendas', [])), 'fotos': len(b.fotos(True))})
            if caminho == '/api/parar':
                self._json(200, {'ok': True})
                parar_rede()
                threading.Thread(target=SERVIDOR_HTTP.shutdown, daemon=True).start()
                return None
            return self._erro(404, 'não encontrado')
        except ValueError as e:
            return self._erro(400, str(e))
        except Exception as e:
            log('erro POST %s: %r' % (caminho, e))
            return self._erro(500, str(e))



# ---------------- certificados da loja (gerador embutido; código em texto para ir junto na atualização pela nuvem) ----------------
import types
CERTIFICADOS_FONTE = r'''# Certificados da loja para o HTTPS na rede local (venda pelo celular), em Python puro (sem bibliotecas externas).
# Gera uma "autoridade" da loja (instalada uma vez em cada celular) e o certificado do servidor com os IPs do computador.
# Se o IP mudar, só o certificado do servidor é refeito; os celulares continuam confiando na autoridade.
import os, json, base64, hashlib, secrets, datetime, socket

NL = chr(10)


# ---------------- RSA ----------------
def _primo_provavel(n, voltas=40):
    if n < 4:
        return n in (2, 3)
    for p in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37):
        if n % p == 0:
            return n == p
    d, s = n - 1, 0
    while d % 2 == 0:
        d //= 2
        s += 1
    for _ in range(voltas):
        a = secrets.randbelow(n - 3) + 2
        x = pow(a, d, n)
        if x in (1, n - 1):
            continue
        for _ in range(s - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


def _primo(bits):
    while True:
        n = secrets.randbits(bits) | (1 << (bits - 1)) | (1 << (bits - 2)) | 1
        if _primo_provavel(n):
            return n


def gerar_rsa(bits=2048):
    e = 65537
    while True:
        p, q = _primo(bits // 2), _primo(bits // 2)
        if p == q:
            continue
        fi = (p - 1) * (q - 1)
        try:
            d = pow(e, -1, fi)
        except ValueError:
            continue
        n = p * q
        if n.bit_length() == bits:
            return {'n': n, 'e': e, 'd': d, 'p': p, 'q': q}


# ---------------- DER (ASN.1) ----------------
def _tam(n):
    if n < 128:
        return bytes([n])
    b = n.to_bytes((n.bit_length() + 7) // 8, 'big')
    return bytes([0x80 | len(b)]) + b


def tlv(tag, conteudo):
    return bytes([tag]) + _tam(len(conteudo)) + conteudo


def inteiro(v):
    b = v.to_bytes(max(1, (v.bit_length() + 8) // 8), 'big')
    return tlv(0x02, b)


def seq(*partes):
    return tlv(0x30, b''.join(partes))


def conj(*partes):
    return tlv(0x31, b''.join(partes))


def oid(texto):
    nums = [int(x) for x in texto.split('.')]
    out = bytes([40 * nums[0] + nums[1]])
    for n in nums[2:]:
        grupo = [n & 0x7f]
        n >>= 7
        while n:
            grupo.append(0x80 | (n & 0x7f))
            n >>= 7
        out += bytes(reversed(grupo))
    return tlv(0x06, out)


def utf8(t):
    return tlv(0x0c, t.encode('utf-8'))


def bits(b):
    return tlv(0x03, bytes([0]) + b)


def octetos(b):
    return tlv(0x04, b)


def tempo(dt):
    return tlv(0x17, dt.strftime('%y%m%d%H%M%SZ').encode('ascii'))


def ctx(n, conteudo, construido=True):
    return tlv((0xa0 if construido else 0x80) | n, conteudo)


SHA256_RSA = seq(oid('1.2.840.113549.1.1.11'), tlv(0x05, b''))


def nome(cn):
    return seq(conj(seq(oid('2.5.4.3'), utf8(cn))), conj(seq(oid('2.5.4.10'), utf8('Controle de Estoque'))))


def chave_publica(k):
    rsa = seq(inteiro(k['n']), inteiro(k['e']))
    return seq(seq(oid('1.2.840.113549.1.1.1'), tlv(0x05, b'')), bits(rsa))


def assinar(k, dados):
    tam = (k['n'].bit_length() + 7) // 8
    info = bytes.fromhex('3031300d060960864801650304020105000420') + hashlib.sha256(dados).digest()
    em = bytes([0, 1]) + bytes([255]) * (tam - 3 - len(info)) + bytes([0]) + info
    return pow(int.from_bytes(em, 'big'), k['d'], k['n']).to_bytes(tam, 'big')


def extensao(o, valor, critica=False):
    return seq(oid(o), *( [tlv(0x01, bytes([255]))] if critica else []), octetos(valor))


def certificado(sujeito, chave_suj, emissor, chave_emissor, dias, ca=False, ips=(), nomes=()):
    agora = datetime.datetime.utcnow() - datetime.timedelta(days=1)
    exts = [extensao('2.5.29.19', seq(tlv(0x01, bytes([255]))) if ca else seq(), True)]
    if ca:
        exts.append(extensao('2.5.29.15', bits(bytes([0x06])), True))   # keyCertSign + cRLSign
    else:
        exts.append(extensao('2.5.29.15', bits(bytes([0xa0])), True))   # digitalSignature + keyEncipherment
        exts.append(extensao('2.5.29.37', seq(oid('1.3.6.1.5.5.7.3.1'))))   # serverAuth
        alt = b''.join(tlv(0x87, socket.inet_aton(ip)) for ip in ips) + b''.join(tlv(0x82, n.encode('ascii')) for n in nomes)
        exts.append(extensao('2.5.29.17', seq(alt)))
    ski = hashlib.sha1(chave_publica(chave_suj)).digest()
    exts.append(extensao('2.5.29.14', octetos(ski)))
    tbs = seq(ctx(0, inteiro(2)), inteiro(secrets.randbits(63)), SHA256_RSA, nome(emissor), seq(tempo(agora), tempo(agora + datetime.timedelta(days=dias))),
              nome(sujeito), chave_publica(chave_suj), ctx(3, seq(*exts)))
    return seq(tbs, SHA256_RSA, bits(assinar(chave_emissor, tbs)))


def pem(rotulo, der):
    b = base64.b64encode(der).decode('ascii')
    return '-----BEGIN ' + rotulo + '-----' + NL + NL.join(b[i:i + 64] for i in range(0, len(b), 64)) + NL + '-----END ' + rotulo + '-----' + NL


def chave_pem(k):
    dp, dq, qi = k['d'] % (k['p'] - 1), k['d'] % (k['q'] - 1), pow(k['q'], -1, k['p'])
    return pem('RSA PRIVATE KEY', seq(inteiro(0), inteiro(k['n']), inteiro(k['e']), inteiro(k['d']), inteiro(k['p']), inteiro(k['q']), inteiro(dp), inteiro(dq), inteiro(qi)))


# ---------------- arquivos da loja ----------------
def ips_locais():
    ips = set()
    try:
        for r in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(r[4][0])
    except OSError:
        pass
    try:   # IP usado para sair para a rede (não envia nada)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(('10.255.255.255', 1)); ips.add(s.getsockname()[0]); s.close()
    except OSError:
        pass
    return sorted(i for i in ips if not i.startswith('127.') and not i.startswith('169.254.'))


def garantir(pasta, nome_loja='Loja'):
    """cria a autoridade (uma vez) e o certificado do servidor (de novo se os IPs mudarem); devolve os caminhos e os IPs"""
    os.makedirs(pasta, exist_ok=True)
    ca_crt, ca_key, srv_crt, srv_key, info = (os.path.join(pasta, n) for n in ('loja-ca.crt', 'loja-ca.json', 'servidor.crt', 'servidor.key', 'servidor.json'))
    if not os.path.exists(ca_key):
        k = gerar_rsa()
        cn = 'Autoridade ' + (nome_loja or 'Loja')[:40] + ' ' + datetime.date.today().isoformat()
        der = certificado(cn, k, cn, k, 3650, ca=True)
        open(ca_crt, 'w', encoding='ascii', newline='').write(pem('CERTIFICATE', der))
        json.dump({'cn': cn, 'n': hex(k['n']), 'e': k['e'], 'd': hex(k['d']), 'p': hex(k['p']), 'q': hex(k['q'])}, open(ca_key, 'w'))
    ca = json.load(open(ca_key))
    kca = {'n': int(ca['n'], 16), 'e': ca['e'], 'd': int(ca['d'], 16), 'p': int(ca['p'], 16), 'q': int(ca['q'], 16)}
    ips, host = ips_locais(), socket.gethostname().lower()
    nomes = sorted({host, host + '.local', 'localhost'})
    atual = json.load(open(info)) if os.path.exists(info) else {}
    vence = atual.get('vence', '')
    if atual.get('ips') != ips or atual.get('nomes') != nomes or not os.path.exists(srv_key) or vence < (datetime.date.today() + datetime.timedelta(days=30)).isoformat():
        k = gerar_rsa()
        der = certificado(host, k, ca['cn'], kca, 800, ips=ips + ['127.0.0.1'], nomes=nomes)   # iPhone aceita no máximo 825 dias
        open(srv_crt, 'w', encoding='ascii', newline='').write(pem('CERTIFICATE', der) + open(ca_crt).read())
        open(srv_key, 'w', encoding='ascii', newline='').write(chave_pem(k))
        json.dump({'ips': ips, 'nomes': nomes, 'vence': (datetime.date.today() + datetime.timedelta(days=799)).isoformat()}, open(info, 'w'))
    return {'ca': ca_crt, 'crt': srv_crt, 'key': srv_key, 'ips': ips, 'host': host}
'''


def _modulo_certificados():
    m = types.ModuleType('certificados')
    exec(CERTIFICADOS_FONTE, m.__dict__)
    return m


# ---------------- venda pelo celular: servidor na rede da loja (HTTPS), só quando o master libera ----------------
import ssl, secrets
PORTA_REDE = int(os.environ.get('LOJA_PORTA_REDE') or 8443)
PORTA_INSTALAR = int(os.environ.get('LOJA_PORTA_INSTALAR') or 8788)
PASTA_CERTS = os.path.join(PASTA_DADOS, 'certs')
TEMPO_SESSAO = 12 * 3600
SESSOES, FALHAS = {}, {}
REDE = {'https': None, 'http': None, 'ips': [], 'host': '', 'erro': ''}
API_REDE_GET = ('/api/status', '/api/dados', '/api/mudancas', '/api/fotos', '/api/eu')
API_REDE_POST = ('/api/gravar', '/api/logs', '/api/login', '/api/sair')
SEGREDOS_USUARIO = ('hash', 'sal', 'iter', 'alg', 'senha')
SO_CAIXA = ('usuarios',)          # coleções que o celular não altera
SO_CAIXA_META = ('config',)       # nem as configurações da loja


def sem_senhas(lista):
    return [{k: v for k, v in u.items() if k not in SEGREDOS_USUARIO} if isinstance(u, dict) else u for u in (lista or [])]


def usuario_por_login(b, login):
    for s in b._lista('usuarios') if 'usuarios' in b.colecoes() else []:
        u = json.loads(s)
        if str(u.get('login', '')).lower() == login:
            return u
    return None


def entrar_rede(b, login, senha):
    login = (login or '').strip().lower()
    f = FALHAS.get(login, {'n': 0, 'ate': 0})
    if f['ate'] > time.time():
        return None, 'muitas senhas erradas: tente de novo em %d minuto(s)' % (int((f['ate'] - time.time()) / 60) + 1)
    u = usuario_por_login(b, login)
    if u and u.get('ativo') is not False and u.get('alg') == 'pbkdf2':
        h = hashlib.pbkdf2_hmac('sha256', (senha or '').encode('utf-8'), str(u.get('sal')).encode('utf-8'), int(u.get('iter') or 210000), 32).hex()
        if h == u.get('hash'):
            FALHAS.pop(login, None)
            tok = secrets.token_urlsafe(32)
            SESSOES[tok] = {'uid': u['id'], 'nome': u.get('nome', ''), 'perfil': u.get('perfil', ''), 'exp': time.time() + TEMPO_SESSAO}
            log('celular: %s entrou' % u.get('nome', login))
            return tok, None
    if u and u.get('alg') != 'pbkdf2':
        return None, 'entre uma vez pelo computador do caixa para atualizar a sua senha'
    f['n'] += 1
    if f['n'] >= 5:
        f = {'n': 0, 'ate': time.time() + 300}
    FALHAS[login] = f
    log('celular: senha errada para "%s"' % login)
    return None, 'usuário ou senha incorretos'


def sessao(tok):
    s = SESSOES.get(tok or '')
    if s and s['exp'] > time.time():
        s['exp'] = time.time() + TEMPO_SESSAO
        return s
    SESSOES.pop(tok or '', None)
    return None


class AtendenteRede(Atendente):
    """mesmo sistema, servido em HTTPS para os celulares da rede: exige login e só libera vender e consultar"""
    def _host_ok(self):
        h = (self.headers.get('Host') or '').lower()
        return h in {'%s:%d' % (x, PORTA_REDE) for x in REDE['ips'] + [REDE['host'], REDE['host'] + '.local', '127.0.0.1', 'localhost']}

    def _barrar(self):
        if not REDE.get('https') or not self._host_ok():   # bloqueado pelo master: conexões já abertas também param
            self.close_connection = True
            return 'acesso negado'
        caminho = self.path.split('?')[0]
        if not caminho.startswith('/api/'):
            return None
        origem = self.headers.get('Origin')
        if origem is not None and origem != 'https://' + (self.headers.get('Host') or '').lower():
            return 'pedido de outro site recusado'
        if (self.headers.get('Sec-Fetch-Site') or '').lower() in ('cross-site', 'same-site'):
            return 'pedido de outro site recusado'
        permitido = caminho.startswith('/api/fotos/') if self.command == 'GET' else False
        if self.command == 'GET' and caminho not in API_REDE_GET and not permitido:
            return 'função disponível só no computador do caixa'
        foto = caminho.startswith('/api/fotos/') and caminho not in ('/api/fotos/lote', '/api/fotos/limpar')   # foto de produto tirada no celular
        if self.command in ('POST', 'PUT') and caminho not in API_REDE_POST and not foto:
            return 'função disponível só no computador do caixa'
        if self.command in ('POST', 'PUT') and self.headers.get(MARCA) != '1':
            return 'pedido sem a marca do sistema recusado'
        if caminho not in ('/api/status', '/api/login') and not sessao(self.headers.get('X-Sessao')):
            return 'SESSAO'
        return None

    def _recusar(self, motivo):
        if motivo == 'SESSAO':
            return self._erro(401, 'entre de novo com o seu usuário e senha')
        return Atendente._recusar(self, motivo)

    def _corpo(self):
        corpo = Atendente._corpo(self)
        caminho = self.path.split('?')[0]
        if caminho.startswith('/api/fotos/'):   # só aceita imagem JPEG/PNG em data URL, até 3 MB
            d = json.loads(corpo.decode('utf-8') or '{}')
            ok = isinstance(d, dict) and all(isinstance(d.get(k), str) and re.match(r'data:image/(jpeg|png);base64,[A-Za-z0-9+/=]+$', d.get(k)) for k in ('img', 'mini')) and len(corpo) < 3 * 1024 * 1024
            if not ok or not re.match(r'[A-Za-z0-9_-]{1,40}$', urllib.parse.unquote(caminho[11:])):
                raise ValueError('foto inválida')
            return json.dumps({'img': d['img'], 'mini': d['mini']}).encode('utf-8')
        if caminho != '/api/gravar':
            return corpo
        d = json.loads(corpo.decode('utf-8') or '{}')   # o celular não grava usuários (senhas) nem configurações
        for nome in SO_CAIXA:
            (d.get('colecoes') or {}).pop(nome, None)
            (d.get('listas') or {}).pop(nome, None)
        m = d.get('meta') or {}
        for k in SO_CAIXA_META:
            (m.get('set') or {}).pop(k, None)
        if m.get('del'):
            m['del'] = [k for k in m['del'] if k not in SO_CAIXA_META]
        return json.dumps(d, ensure_ascii=False).encode('utf-8')

    def do_GET(self):
        caminho = self.path.split('?')[0]
        if caminho in ('/api/dados', '/api/mudancas'):   # mesmos dados, sem as senhas (hash) das pessoas
            motivo = self._barrar()
            if motivo:
                return self._recusar(motivo)
            b = BANCO_ATIVO
            try:
                if caminho == '/api/dados':
                    ver = b.versao()
                    d = json.loads(b.ler_dados()) if not b.vazio() else {}
                    if isinstance(d.get('usuarios'), list):
                        d['usuarios'] = sem_senhas(d['usuarios'])
                    corpo = json.dumps(d, ensure_ascii=False)
                    return self._enviar(200, '{"versao":%d,"dados":%s}' % (ver, corpo) if 'versao=1' in self.path else corpo)
                q = urllib.parse.parse_qs(self.path.split('?', 1)[1] if '?' in self.path else '')
                m = json.loads(b.mudancas(int((q.get('desde') or ['0'])[0] or 0), (q.get('cliente') or [''])[0]))
                for grupo in ('colecoes', 'listas'):
                    if isinstance((m.get(grupo) or {}).get('usuarios'), list):
                        m[grupo]['usuarios'] = sem_senhas(m[grupo]['usuarios'])
                return self._enviar(200, json.dumps(m, ensure_ascii=False))
            except Exception as e:
                log('erro GET %s (celular): %r' % (caminho, e))
                return self._erro(500, str(e))
        if caminho in ('/api/status', '/api/eu'):
            motivo = self._barrar()
            if motivo:
                return self._recusar(motivo)
            if caminho == '/api/eu':
                s = sessao(self.headers.get('X-Sessao'))
                return self._json(200, {'uid': s['uid'], 'nome': s['nome']})
            cfg = BANCO_ATIVO.config()   # nome e logo da loja para a tela de entrada do celular (já aparecem em qualquer recibo)
            tema = cfg.get('tema') if isinstance(cfg.get('tema'), dict) else {}
            return self._json(200, {'app': 'lojaRoupas', 'servidor': VERSAO_SERVIDOR, 'rede': True, 'licenca': situacao_licenca(BANCO_ATIVO, cfg),
                                    'loja': cfg.get('loja') or '', 'logo': tema.get('logoTela') or cfg.get('logo') or ''})
        return Atendente.do_GET(self)

    def do_POST(self):
        caminho = self.path.split('?')[0]
        if caminho in ('/api/login', '/api/sair'):
            motivo = self._barrar()
            if motivo:
                return self._recusar(motivo)
            try:
                dados = json.loads(self._corpo().decode('utf-8') or '{}')
            except Exception:
                return self._erro(400, 'pedido inválido')
            if caminho == '/api/sair':
                SESSOES.pop(self.headers.get('X-Sessao') or '', None)
                return self._json(200, {'ok': True})
            tok, erro = entrar_rede(BANCO_ATIVO, dados.get('login'), dados.get('senha'))
            if not tok:
                return self._erro(401, erro)
            s = SESSOES[tok]
            return self._json(200, {'ok': True, 'sessao': tok, 'uid': s['uid'], 'nome': s['nome']})
        return Atendente.do_POST(self)


class AtendenteInstalar(BaseHTTPRequestHandler):
    """porta sem HTTPS só para o celular baixar a autoridade da loja e ver como instalar"""
    def log_message(self, *a):
        pass

    def do_GET(self):
        caminho = self.path.split('?')[0]
        host = (self.headers.get('Host') or '').split(':')[0]
        if caminho == '/loja-ca.crt':
            corpo, tipo = open(os.path.join(PASTA_CERTS, 'loja-ca.crt'), 'rb').read(), 'application/x-x509-ca-cert'
            extra = [('Content-Disposition', 'attachment; filename="loja-ca.crt"')]
        elif caminho == '/':
            url = 'https://%s:%d/' % (host, PORTA_REDE)
            corpo = PAGINA_INSTALAR.replace('{{URL}}', url).replace('{{CA}}', '/loja-ca.crt').encode('utf-8')
            tipo, extra = 'text/html; charset=utf-8', []
        else:
            corpo, tipo, extra = b'nao encontrado', 'text/plain', []
            self.send_response(404)
        if caminho in ('/', '/loja-ca.crt'):
            self.send_response(200)
        self.send_header('Content-Type', tipo)
        self.send_header('Content-Length', str(len(corpo)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Frame-Options', 'DENY')
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(corpo)


PAGINA_INSTALAR = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Instalar no celular</title>
<style>body{font-family:system-ui,sans-serif;margin:0;background:#f4f5f7;color:#141a26}.cx{max-width:560px;margin:0 auto;padding:20px}h1{font-size:22px}
.passo{background:#fff;border:1px solid #e7e9ee;border-radius:14px;padding:14px 16px;margin:12px 0}.b{display:block;text-align:center;background:#16213a;color:#fff;padding:14px;border-radius:12px;text-decoration:none;font-weight:700;margin-top:10px}
small{color:#6b7385}</style></head><body><div class="cx"><h1>Controle de Estoque no celular</h1>
<div class="passo"><b>1. Instale o certificado da loja</b> (só uma vez neste celular)<a class="b" href="{{CA}}">Baixar certificado da loja</a>
<p><b>iPhone:</b> toque em Permitir · abra Ajustes → Perfil Transferido → Instalar. Depois: Ajustes → Geral → Sobre → Ajustes de Confiança de Certificados → ligue a chave da loja.</p>
<p><b>Android:</b> Configurações → Segurança → Mais configurações → Criptografia e credenciais → Instalar um certificado → Certificado de CA → escolha <i>loja-ca.crt</i> (o nome do menu muda um pouco conforme o celular).</p></div>
<div class="passo"><b>2. Abra o sistema</b><a class="b" href="{{URL}}">Abrir o Controle de Estoque</a><p><small>Dica: no menu do navegador, use "Adicionar à tela inicial" para abrir como aplicativo.</small></p></div>
<p><small>O celular precisa estar no Wi-Fi da loja. Se aparecer aviso de "conexão não particular", o certificado do passo 1 ainda não foi instalado ou não foi marcado como confiável.</small></p></div></body></html>"""


def iniciar_rede():
    certificados = _modulo_certificados()
    parar_rede()
    try:
        cfg = BANCO_ATIVO.config() if BANCO_ATIVO else {}
        c = certificados.garantir(PASTA_CERTS, cfg.get('loja') or 'Loja')
        REDE.update(ips=c['ips'], host=c['host'], erro='')
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(c['crt'], c['key'])
        s1 = ThreadingHTTPServer(('0.0.0.0', PORTA_REDE), AtendenteRede)
        s1.socket = ctx.wrap_socket(s1.socket, server_side=True)
        s2 = ThreadingHTTPServer(('0.0.0.0', PORTA_INSTALAR), AtendenteInstalar)
        for s in (s1, s2):
            threading.Thread(target=s.serve_forever, daemon=True).start()
        REDE.update(https=s1, http=s2)
        log('venda pelo celular LIGADA: https://%s:%d/ (instalar: http://%s:%d/)' % ((c['ips'] or ['?'])[0], PORTA_REDE, (c['ips'] or ['?'])[0], PORTA_INSTALAR))
        return True
    except Exception as e:
        REDE['erro'] = str(e)
        log('venda pelo celular: não foi possível ligar: %r' % e)
        parar_rede()
        return False


def parar_rede():
    for k in ('https', 'http'):
        if REDE.get(k):
            try:
                REDE[k].shutdown()
                REDE[k].server_close()
            except Exception:
                pass
            REDE[k] = None
    SESSOES.clear()


def info_rede():
    ip = (REDE['ips'] or [''])[0]
    return {'ativo': bool(REDE.get('https')), 'liberado': bool(BANCO_ATIVO and BANCO_ATIVO.meta_interna('rede')), 'ips': REDE['ips'], 'host': REDE['host'], 'erro': REDE['erro'],
            'endereco': 'https://%s:%d/' % (ip, PORTA_REDE) if ip else '', 'instalar': 'http://%s:%d/' % (ip, PORTA_INSTALAR) if ip else '', 'sessoes': len([s for s in SESSOES.values() if s['exp'] > time.time()])}


# ---------------- iniciar / abrir ----------------
def status():
    try:
        with urllib.request.urlopen('http://127.0.0.1:%d/api/status' % PORTA, timeout=1.5) as r:
            j = json.loads(r.read().decode('utf-8'))
            return j if j.get('app') == 'lojaRoupas' else None
    except Exception:
        return None


def servir():
    global BANCO_ATIVO, SERVIDOR_HTTP
    for tentativa in range(60 if '--esperar' in sys.argv else 1):
        try:
            SERVIDOR_HTTP = ThreadingHTTPServer(('127.0.0.1', PORTA), Atendente)
            break
        except OSError:
            time.sleep(0.5)
    else:
        log('porta %d ocupada; servidor não iniciado (já está rodando?)' % PORTA)
        return False
    BANCO_ATIVO = Banco(BANCO)
    threading.Thread(target=laco_copias, args=(BANCO_ATIVO,), daemon=True).start()
    if BANCO_ATIVO.meta_interna('rede'):
        for _ in range(20):   # depois de uma atualização, a porta da rede pode levar alguns segundos para ficar livre
            if iniciar_rede():
                break
            time.sleep(0.5)
    log('servidor %s iniciado em http://127.0.0.1:%d (pasta %s)' % (VERSAO_SERVIDOR, PORTA, BASE))
    SERVIDOR_HTTP.serve_forever()
    log('servidor parado')
    return True


def navegador():
    pf, pf86, lad = os.environ.get('ProgramFiles', ''), os.environ.get('ProgramFiles(x86)', ''), os.environ.get('LOCALAPPDATA', '')
    for c in (os.path.join(pf86, 'Microsoft', 'Edge', 'Application', 'msedge.exe'), os.path.join(pf, 'Microsoft', 'Edge', 'Application', 'msedge.exe'),
              os.path.join(lad, 'Microsoft', 'Edge', 'Application', 'msedge.exe'), os.path.join(pf, 'Google', 'Chrome', 'Application', 'chrome.exe'),
              os.path.join(pf86, 'Google', 'Chrome', 'Application', 'chrome.exe'), os.path.join(lad, 'Google', 'Chrome', 'Application', 'chrome.exe')):
        if c and os.path.exists(c):
            return c
    return None


def aviso_windows(msg):
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, msg, 'Controle de Estoque', 0x30)
    except Exception:
        print(msg)


def abrir():
    st = status()
    if not st:
        exe = sys.executable
        if os.path.basename(exe).lower() == 'python.exe' and os.path.exists(os.path.join(os.path.dirname(exe), 'pythonw.exe')):
            exe = os.path.join(os.path.dirname(exe), 'pythonw.exe')
        subprocess.Popen([exe, os.path.abspath(__file__), '--servico'], cwd=BASE, creationflags=0x00000008 | 0x00000200, close_fds=True)
        for _ in range(60):
            time.sleep(0.25)
            st = status()
            if st:
                break
    if not st:
        aviso_windows('O servidor do Controle de Estoque não iniciou. Reinicie o computador; se continuar, avise o suporte.' + NL + NL + 'Registro: ' + ARQ_LOG)
        return 1
    url = 'http://127.0.0.1:%d/' % PORTA
    if st.get('vazio') and not st.get('migradoEm') and os.path.exists(ARQ_MIGRAR):
        url = 'file:///' + ARQ_MIGRAR.replace(os.sep, '/') + '?p=%d' % PORTA
    nav = navegador()
    if nav:
        subprocess.Popen([nav, '--app=' + url, '--start-maximized'])
    else:
        os.startfile(url)
    return 0


def parar():
    try:
        req = urllib.request.Request('http://127.0.0.1:%d/api/parar' % PORTA, data=b'{}', method='POST', headers={'Content-Type': 'application/json'})
        urllib.request.urlopen(req, timeout=3).read()
    except Exception:
        pass
    for _ in range(20):
        if not status():
            return 0
        time.sleep(0.25)
    return 1


if __name__ == '__main__':
    arg = sys.argv[1] if len(sys.argv) > 1 else '--abrir'
    if arg == '--servico':
        servir()
    elif arg == '--parar':
        sys.exit(parar())
    elif arg == '--status':
        print(json.dumps(status(), ensure_ascii=False, indent=1))
    else:
        sys.exit(abrir())
