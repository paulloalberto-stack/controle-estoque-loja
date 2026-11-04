# Controle de Estoque – © 2026 P.A.S Soluções Tecnológicas. Todos os direitos reservados.
# Servidor local do Controle de Estoque.
# Entrega o sistema em http://127.0.0.1:8787 e grava os dados da loja no banco SQLite dados/loja.sqlite
# (limpar os dados do navegador não apaga mais nada). Só aceita conexões deste computador.
#   pythonw servidor.py --abrir    inicia o servidor (se não estiver rodando) e abre o sistema no Edge
#   pythonw servidor.py --servico  só o servidor (início com o Windows)
#   python  servidor.py --parar    para o servidor (usado pelo instalador)
import os, sys, json, sqlite3, threading, hashlib, base64, re, time, datetime, subprocess, struct, urllib.request, urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

VERSAO_SERVIDOR = '2026.11.04-01'
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
RESERVADAS = {'meta', 'fotos', 'logs', 'copias', 'colecoes', 'sqlite_sequence'}
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
        ok = self.c.execute('PRAGMA quick_check').fetchone()[0]
        log('banco aberto: ' + caminho + ' (verificação: ' + ok + ')')

    def colecoes(self):
        return [r[0] for r in self.c.execute('SELECT nome FROM colecoes')]

    def _lista(self, nome):
        if nome not in self.cache:
            self.cache[nome] = [r[0] for r in self.c.execute('SELECT registro FROM "%s" ORDER BY pos' % nome)]
        return self.cache[nome]

    def vazio(self):
        r = self.c.execute("SELECT valor FROM meta WHERE chave='_salvo'").fetchone()
        return r is None

    def ler_dados(self):
        with self.trava:
            partes = []
            for chave, valor in self.c.execute("SELECT chave, valor FROM meta WHERE substr(chave, 1, 2) <> '__'"):
                partes.append(json.dumps(chave) + ':' + valor)
            for nome in self.colecoes():
                partes.append(json.dumps(nome) + ':[' + ','.join(self._lista(nome)) + ']')
            return '{' + ','.join(partes) + '}'

    def gravar_dados(self, obj, forcar=False):
        if not isinstance(obj, dict) or not isinstance(obj.get('usuarios'), list) or not isinstance(obj.get('produtos'), list):
            raise ValueError('dados inválidos')
        with self.trava:
            atual = self.c.execute("SELECT valor FROM meta WHERE chave='_salvo'").fetchone()
            if atual and not forcar and float(json.loads(atual[0]) or 0) > float(obj.get('_salvo') or 0):
                return False
            listas = {k: v for k, v in obj.items() if isinstance(v, list) and NOME_OK.match(k) and k not in RESERVADAS}
            novas_cache = {}
            self.c.execute('BEGIN IMMEDIATE')
            try:
                existentes = set(self.colecoes())
                for nome, lista in listas.items():
                    if nome not in existentes:
                        self.c.execute('CREATE TABLE IF NOT EXISTS "%s"(pos INTEGER PRIMARY KEY, id TEXT, registro TEXT NOT NULL)' % nome)
                        self.c.execute('INSERT OR IGNORE INTO colecoes(nome) VALUES(?)', (nome,))
                        velhas = []
                    else:
                        velhas = self._lista(nome)
                    novas = [json.dumps(x, ensure_ascii=False, separators=(',', ':')) for x in lista]
                    for i, s in enumerate(novas):
                        if i >= len(velhas) or velhas[i] != s:
                            ident = lista[i].get('id') if isinstance(lista[i], dict) else None
                            self.c.execute('INSERT OR REPLACE INTO "%s"(pos, id, registro) VALUES(?,?,?)' % nome, (i, None if ident is None else str(ident), s))
                    if len(velhas) > len(novas):
                        self.c.execute('DELETE FROM "%s" WHERE pos >= ?' % nome, (len(novas),))
                    novas_cache[nome] = novas
                for nome in existentes - set(listas):
                    self.c.execute('DELETE FROM "%s"' % nome)
                    novas_cache[nome] = []
                outros = {k: v for k, v in obj.items() if k not in listas}
                self.c.execute("DELETE FROM meta WHERE substr(chave, 1, 2) <> '__'")
                for k, v in outros.items():
                    self.c.execute('INSERT OR REPLACE INTO meta(chave, valor) VALUES(?,?)', (k, json.dumps(v, ensure_ascii=False, separators=(',', ':'))))
                self.c.execute('COMMIT')
            except Exception:
                self.c.execute('ROLLBACK')
                self.cache = {}
                raise
            self.cache.update(novas_cache)
            return True

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
                                        'pasta': BASE, 'backups': PASTA_BACKUP, 'pastaExtra': b.meta_interna('pastaExtra') or '', 'iconeHash': b.meta_interna('iconeHash') or '', 'icone': icone_atual(), 'licenca': situacao_licenca(b, b.config())})
            if caminho == '/api/dados':
                return self._enviar(200, b.ler_dados() if not b.vazio() else '{}')
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
                threading.Thread(target=SERVIDOR_HTTP.shutdown, daemon=True).start()
                return None
            return self._erro(404, 'não encontrado')
        except ValueError as e:
            return self._erro(400, str(e))
        except Exception as e:
            log('erro POST %s: %r' % (caminho, e))
            return self._erro(500, str(e))


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
