(function () {
  var base = JSON.parse(document.getElementById('state').textContent);
  var key = 'fb-sprint:' + base.sprintId;
  var cur = base;
  try { var saved = JSON.parse(localStorage.getItem(key) || 'null'); if (saved && saved.updatedAt > base.updatedAt) cur = saved; } catch (e) {}
  var cards = [].slice.call(document.querySelectorAll('article.card'));
  var segs = [[0], [1], [2], [3, 4], [5], [6]]; // порядок сегментов прогресса
  var pcls = ['p0', 'p1', 'p2', 'p3', 'p3', 'p4'];

  function save() { cur.updatedAt = Date.now(); try { localStorage.setItem(key, JSON.stringify(cur)); } catch (e) {} }

  function paint(card) {
    var id = card.id, st = cur.statuses[id];
    card.setAttribute('data-status', st);
    [].forEach.call(card.querySelectorAll('.step'), function (b) {
      var n = Number(b.getAttribute('data-s'));
      b.classList.toggle('cur', n === st);
      b.classList.toggle('done', st <= 4 && n < st);
      b.setAttribute('aria-pressed', n === st ? 'true' : 'false');
    });
    [].forEach.call(card.querySelectorAll('.side button'), function (b) {
      b.setAttribute('aria-pressed', Number(b.getAttribute('data-s')) === st ? 'true' : 'false');
    });
  }

  function progress() {
    var counts = {}, total = cards.length;
    cards.forEach(function (c) { var s = cur.statuses[c.id]; counts[s] = (counts[s] || 0) + 1; });
    var bar = document.getElementById('bar'), pkey = document.getElementById('pkey');
    var labels = ['Не взято', 'В работе', 'Ревью', 'Смержено или на проде', 'Готово без PR', 'Нужен человек'];
    var colors = ['p0', 'p1', 'p2', 'p3', 'p3', 'p4'];
    bar.innerHTML = ''; pkey.innerHTML = '';
    segs.forEach(function (g, i) {
      var n = g.reduce(function (a, s) { return a + (counts[s] || 0); }, 0);
      if (!n) return;
      var sp = document.createElement('span'); sp.className = colors[i]; sp.style.flex = n; sp.title = labels[i] + ': ' + n; bar.appendChild(sp);
      var k = document.createElement('span'); k.innerHTML = '<i class="' + colors[i] + '"></i>' + labels[i] + ' ' + n; pkey.appendChild(k);
    });
  }

  cards.forEach(function (card) {
    if (cur.statuses[card.id] === undefined) cur.statuses[card.id] = 0;
    paint(card);
    card.addEventListener('click', function (ev) {
      var b = ev.target.closest('button[data-s]');
      if (!b) return;
      var n = Number(b.getAttribute('data-s'));
      cur.statuses[card.id] = (cur.statuses[card.id] === n && n > 4) ? 0 : n;
      save(); paint(card); progress(); filter();
    });
  });

  var fl = { tier: 'all', theme: 'all', st: 'all' };
  function filter() {
    var shown = 0;
    cards.forEach(function (c) {
      var st = cur.statuses[c.id];
      var ok = (fl.tier === 'all' || c.getAttribute('data-tier') === fl.tier) &&
               (fl.theme === 'all' || c.getAttribute('data-theme') === fl.theme) &&
               (fl.st === 'all' || (fl.st === 'open' ? st < 4 : st >= 4));
      c.hidden = !ok; if (ok) shown++;
    });
    document.getElementById('count').textContent = shown + ' из ' + cards.length;
  }
  [].forEach.call(document.querySelectorAll('[data-f]'), function (b) {
    b.addEventListener('click', function () {
      var f = b.getAttribute('data-f'), v = b.getAttribute('data-v');
      fl[f] = v;
      [].forEach.call(document.querySelectorAll('[data-f="' + f + '"]'), function (x) { x.setAttribute('aria-pressed', x === b ? 'true' : 'false'); });
      filter();
    });
  });
  document.getElementById('theme').addEventListener('change', function () { fl.theme = this.value; filter(); });
  var allOpen = false;
  document.getElementById('toggleAll').addEventListener('click', function () {
    allOpen = !allOpen;
    [].forEach.call(document.querySelectorAll('details.more'), function (d) { d.open = allOpen; });
    this.textContent = allOpen ? 'Свернуть подробности' : 'Развернуть подробности';
  });
  document.getElementById('export').addEventListener('click', function () {
    var blob = new Blob([JSON.stringify({ updatedAt: cur.updatedAt, statuses: cur.statuses }, null, 1)], { type: 'application/json' });
    var a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'sprint_status.json'; a.click();
  });

  // галочки «что нужно от людей»
  var hkey = 'fb-human:' + base.sprintId, hs = {};
  try { hs = JSON.parse(localStorage.getItem(hkey) || '{}'); } catch (e) {}
  [].forEach.call(document.querySelectorAll('input[data-h]'), function (c) {
    var h = c.getAttribute('data-h'); c.checked = !!hs[h];
    c.addEventListener('change', function () { hs[h] = c.checked; try { localStorage.setItem(hkey, JSON.stringify(hs)); } catch (e) {} });
  });
  progress(); filter();
})();
