#!/usr/bin/env python3
"""Учебное Todo-приложение для практической работы 8 (E2E-тесты, Playwright).

Запуск:  python server.py              (порт 8000, или переменная PORT)
Логин:   user / user123

Переменные окружения:
  PORT             порт (по умолчанию 8000)
  TODO_TEST_MODE   "1" включает служебный POST /api/test/reset (только для тестов)
  TODO_DELAY_MS    искусственная задержка ответов /api/todos, мс (для разбора flaky-тестов)
"""
import json
import os
import re
import secrets
import threading
import time
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

USERS = {"user": "user123"}
SESSIONS = {}   # токен -> имя пользователя
TODOS = {}      # имя пользователя -> список задач
NEXT_ID = {}    # имя пользователя -> последний выданный id (id не переиспользуются)
LOCK = threading.Lock()
MAX_LEN = 100
TEST_MODE = os.environ.get("TODO_TEST_MODE") == "1"
DELAY_MS = int(os.environ.get("TODO_DELAY_MS", "0") or 0)

STYLE = """
<style>
  body { font-family: Arial, sans-serif; margin: 0; background: #f4f6f8; color: #222; }
  main { max-width: 560px; margin: 32px auto; background: #fff; padding: 24px; border-radius: 8px; }
  header { display: flex; align-items: center; gap: 12px; }
  header h1 { flex: 1; margin: 0; font-size: 24px; }
  form { display: flex; gap: 8px; margin: 16px 0 8px; }
  form input[type=text], form input[type=password] { flex: 1; padding: 8px; }
  label { display: block; margin-top: 8px; }
  button { padding: 8px 12px; cursor: pointer; }
  [hidden] { display: none !important; }
  #error, #login-error { color: #b00020; margin: 4px 0; }
  .filters { display: flex; gap: 8px; margin: 12px 0; }
  .filters button[aria-pressed=true] { background: #1f4e79; color: #fff; }
  ul { list-style: none; padding: 0; margin: 0; }
  li { display: flex; align-items: center; gap: 8px; padding: 8px 0; border-bottom: 1px solid #eee; }
  li .title { flex: 1; }
  li.done .title { text-decoration: line-through; color: #888; }
</style>
"""

LOGIN_HTML = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><title>Вход</title>""" + STYLE + """</head>
<body><main>
  <h1>Вход</h1>
  <form id="login-form">
    <div>
      <label for="username">Логин</label>
      <input id="username" name="username" type="text" autocomplete="username">
      <label for="password">Пароль</label>
      <input id="password" name="password" type="password" autocomplete="current-password">
      <p><button type="submit">Войти</button></p>
    </div>
  </form>
  <p id="login-error" role="alert" hidden></p>
</main>
<script>
  const err = document.getElementById('login-error');
  document.getElementById('login-form').addEventListener('submit', async (ev) => {
    ev.preventDefault();
    err.hidden = true;
    try {
      const r = await fetch('/api/login', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          username: document.getElementById('username').value,
          password: document.getElementById('password').value,
        }),
      });
      if (r.ok) { location.href = '/'; return; }
      const data = await r.json().catch(() => ({}));
      err.textContent = data.error || 'Ошибка сервера. Попробуйте ещё раз.';
    } catch (e) {
      err.textContent = 'Ошибка сети. Попробуйте ещё раз.';
    }
    err.hidden = false;
  });
</script></body></html>
"""

APP_HTML = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><title>Список задач</title>""" + STYLE + """</head>
<body><main>
  <header>
    <h1>Список задач</h1>
    <button id="logout" type="button">Выйти</button>
  </header>
  <form id="add-form">
    <input id="new-title" type="text" placeholder="Что нужно сделать?" aria-label="Новая задача" autocomplete="off">
    <button type="submit">Добавить</button>
  </form>
  <p id="error" role="alert" hidden></p>
  <div class="filters" role="group" aria-label="Фильтр задач">
    <button type="button" data-filter="all">Все</button>
    <button type="button" data-filter="active">Активные</button>
    <button type="button" data-filter="done">Выполненные</button>
  </div>
  <ul id="list"></ul>
  <p id="empty" hidden>Задач пока нет</p>
  <p id="counter">Осталось: 0</p>
</main>
<script>
  let todos = [];
  let filter = 'all';
  const $ = (id) => document.getElementById(id);

  function showError(msg) { const e = $('error'); e.textContent = msg; e.hidden = false; }
  function clearError() { const e = $('error'); e.textContent = ''; e.hidden = true; }

  function api(path, options) {
    return fetch(path, Object.assign({headers: {'Content-Type': 'application/json'}}, options));
  }

  let loadSeq = 0;
  async function load() {
    const seq = ++loadSeq;
    try {
      const r = await api('/api/todos');
      if (seq !== loadSeq) return;  // пришёл устаревший ответ: игнорируем
      if (r.status === 401) { location.href = '/login'; return; }
      if (!r.ok) throw new Error('bad status');
      todos = await r.json();
      clearError();
    } catch (e) {
      if (seq !== loadSeq) return;
      showError('Не удалось загрузить задачи. Попробуйте ещё раз.');
    }
    render();
  }

  function render() {
    const list = $('list');
    list.textContent = '';
    const shown = todos.filter((t) =>
      filter === 'all' || (filter === 'active' && !t.done) || (filter === 'done' && t.done));
    for (const t of shown) {
      const li = document.createElement('li');
      li.dataset.testid = 'todo-item';
      if (t.done) li.classList.add('done');

      const box = document.createElement('input');
      box.type = 'checkbox';
      box.checked = t.done;
      box.setAttribute('aria-label', 'Выполнено: ' + t.title);
      box.addEventListener('change', () => toggle(t.id, box.checked));

      const title = document.createElement('span');
      title.className = 'title';
      title.dataset.testid = 'todo-title';
      title.textContent = t.title;

      const del = document.createElement('button');
      del.type = 'button';
      del.textContent = 'Удалить';
      del.setAttribute('aria-label', 'Удалить: ' + t.title);
      del.addEventListener('click', () => remove(t.id));

      li.append(box, title, del);
      list.append(li);
    }
    $('counter').textContent = 'Осталось: ' + todos.filter((t) => !t.done).length;
    $('empty').hidden = shown.length > 0;
    document.querySelectorAll('.filters button').forEach((b) =>
      b.setAttribute('aria-pressed', String(b.dataset.filter === filter)));
  }

  async function toggle(id, done) {
    try {
      const r = await api('/api/todos/' + id, {method: 'PATCH', body: JSON.stringify({done})});
      if (!r.ok) showError('Не удалось обновить задачу.');
    } catch (e) { showError('Ошибка сети. Попробуйте ещё раз.'); }
    await load();
  }

  async function remove(id) {
    try {
      const r = await api('/api/todos/' + id, {method: 'DELETE'});
      if (!r.ok && r.status !== 404) showError('Не удалось удалить задачу.');
    } catch (e) { showError('Ошибка сети. Попробуйте ещё раз.'); }
    await load();
  }

  $('add-form').addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const title = $('new-title').value;
    try {
      const r = await api('/api/todos', {method: 'POST', body: JSON.stringify({title})});
      const data = await r.json().catch(() => ({}));
      if (r.status === 201) {
        // очищаем поле, только если пользователь не успел ввести другой текст
        if ($('new-title').value === title) $('new-title').value = '';
        await load();
      } else {
        showError(data.error || 'Ошибка сервера. Попробуйте ещё раз.');
      }
    } catch (e) {
      showError('Ошибка сети. Попробуйте ещё раз.');
    }
  });

  document.querySelectorAll('.filters button').forEach((b) =>
    b.addEventListener('click', () => { filter = b.dataset.filter; render(); }));

  $('logout').addEventListener('click', async () => {
    await api('/api/logout', {method: 'POST', body: '{}'});
    location.href = '/login';
  });

  load();
</script></body></html>
"""

ITEM_PATH = re.compile(r"^/api/todos/(\d+)$")


class Handler(BaseHTTPRequestHandler):
    server_version = "TodoApp/1.0"

    def log_message(self, fmt, *args):
        pass

    # ---------- вспомогательные методы ----------
    def send_bytes(self, status, body=b"", ctype="application/json; charset=utf-8", extra=None):
        self.send_response(status)
        if status != 204:
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
        for key, value in (extra or []):
            self.send_header(key, value)
        self.end_headers()
        if status != 204:
            self.wfile.write(body)

    def send_json(self, status, obj, extra=None):
        self.send_bytes(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"), extra=extra)

    def read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            data = json.loads(raw.decode("utf-8")) if raw else {}
        except ValueError:
            return None
        return data if isinstance(data, dict) else None

    def session_token(self):
        header = self.headers.get("Cookie")
        if not header:
            return None
        jar = cookies.SimpleCookie()
        try:
            jar.load(header)
        except cookies.CookieError:
            return None
        morsel = jar.get("session")
        return morsel.value if morsel else None

    def current_user(self):
        token = self.session_token()
        return SESSIONS.get(token) if token else None

    def delay(self):
        if DELAY_MS:
            time.sleep(DELAY_MS / 1000)

    def require_user(self):
        user = self.current_user()
        if not user:
            self.send_json(401, {"error": "Требуется вход"})
        return user

    # ---------- GET ----------
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            return self.send_json(200, {"status": "ok"})
        if path == "/login":
            return self.send_bytes(200, LOGIN_HTML.encode("utf-8"), "text/html; charset=utf-8")
        if path == "/":
            if not self.current_user():
                return self.send_bytes(302, b"", "text/plain", extra=[("Location", "/login")])
            return self.send_bytes(200, APP_HTML.encode("utf-8"), "text/html; charset=utf-8")
        if path == "/api/todos":
            user = self.require_user()
            if not user:
                return
            self.delay()
            with LOCK:
                items = list(TODOS.get(user, []))
            return self.send_json(200, items)
        self.send_json(404, {"error": "Не найдено"})

    # ---------- POST ----------
    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/login":
            data = self.read_json() or {}
            username, password = data.get("username"), data.get("password")
            if isinstance(username, str) and isinstance(password, str) and USERS.get(username) == password:
                token = secrets.token_hex(16)
                with LOCK:
                    SESSIONS[token] = username
                cookie = f"session={token}; Path=/; HttpOnly; SameSite=Lax"
                return self.send_json(200, {"ok": True}, extra=[("Set-Cookie", cookie)])
            return self.send_json(401, {"error": "Неверный логин или пароль"})

        if path == "/api/logout":
            token = self.session_token()
            with LOCK:
                SESSIONS.pop(token, None)
            cookie = "session=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax"
            return self.send_json(200, {"ok": True}, extra=[("Set-Cookie", cookie)])

        if path == "/api/test/reset":
            if not TEST_MODE:
                return self.send_json(404, {"error": "Не найдено"})
            with LOCK:
                TODOS.clear()
                NEXT_ID.clear()
            return self.send_bytes(204)

        if path == "/api/todos":
            user = self.require_user()
            if not user:
                return
            self.delay()
            data = self.read_json()
            title = data.get("title") if data else None
            title = title.strip() if isinstance(title, str) else ""
            if not title:
                return self.send_json(422, {"error": "Название не может быть пустым"})
            if len(title) > MAX_LEN:
                return self.send_json(422, {"error": f"Название не длиннее {MAX_LEN} символов"})
            with LOCK:
                items = TODOS.setdefault(user, [])
                if any(t["title"].casefold() == title.casefold() for t in items):
                    status, result = 409, {"error": "Такая задача уже есть"}
                else:
                    new_id = NEXT_ID.get(user, 0) + 1
                    NEXT_ID[user] = new_id
                    result = {"id": new_id, "title": title, "done": False}
                    items.append(result)
                    status = 201
            return self.send_json(status, result)

        self.send_json(404, {"error": "Не найдено"})

    # ---------- PATCH ----------
    def do_PATCH(self):
        path = urlparse(self.path).path
        match = ITEM_PATH.match(path)
        if not match:
            return self.send_json(404, {"error": "Не найдено"})
        user = self.require_user()
        if not user:
            return
        self.delay()
        data = self.read_json()
        if not data or not isinstance(data.get("done"), bool):
            return self.send_json(422, {"error": "Поле done должно быть true или false"})
        todo_id = int(match.group(1))
        with LOCK:
            todo = next((t for t in TODOS.get(user, []) if t["id"] == todo_id), None)
            if todo:
                todo["done"] = data["done"]
        if not todo:
            return self.send_json(404, {"error": "Задача не найдена"})
        self.send_json(200, todo)

    # ---------- DELETE ----------
    def do_DELETE(self):
        path = urlparse(self.path).path
        match = ITEM_PATH.match(path)
        if not match:
            return self.send_json(404, {"error": "Не найдено"})
        user = self.require_user()
        if not user:
            return
        self.delay()
        todo_id = int(match.group(1))
        with LOCK:
            items = TODOS.get(user, [])
            before = len(items)
            items[:] = [t for t in items if t["id"] != todo_id]
            removed = len(items) < before
        if not removed:
            return self.send_json(404, {"error": "Задача не найдена"})
        self.send_bytes(204)


def main():
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Todo app: http://127.0.0.1:{port}  (test mode: {TEST_MODE}, delay: {DELAY_MS} ms)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
