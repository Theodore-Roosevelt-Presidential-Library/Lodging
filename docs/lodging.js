/*! TRPL Lodging Finder | Theodore Roosevelt Presidential Library | lodging.labs.trlibrary.com
 *
 * Embed:
 *   <div id="trpl-lodging"></div>
 *   <script src="https://lodging.labs.trlibrary.com/lodging.js" defer></script>
 *
 * Optional attributes on the script tag:
 *   data-target="#some-id"   mount somewhere other than #trpl-lodging
 *   data-heading="off"       hide the built-in heading (when the page has its own)
 *   data-area="medora"       show only Medora-area lodging
 *   data-photos="off"        never show photos
 *   data-photos="all"        also show small photos in the "check directly" lists
 */
(function () {
  'use strict';

  var script = document.currentScript;
  var BASE = script && script.src ? new URL('.', script.src).href : './';
  var opts = (script && script.dataset) || {};
  var host = (opts.target && document.querySelector(opts.target)) || document.getElementById('trpl-lodging');
  if (!host) {
    host = document.createElement('div');
    host.id = 'trpl-lodging';
    if (script && script.parentNode) script.parentNode.insertBefore(host, script);
    else document.body.appendChild(host);
  }
  if (host.shadowRoot) return;
  var root = host.attachShadow({ mode: 'open' });

  var STALE_DAYS = 10;
  var MAX_NIGHTS = 7;
  var TYPES = [
    { key: 'all', label: 'All' },
    { key: 'hotel', label: 'Hotels and inns' },
    { key: 'cabin', label: 'Cabins and rentals' },
    { key: 'camping', label: 'Camping and RV' }
  ];
  var TYPE_NAME = { hotel: 'Hotel or inn', cabin: 'Cabin or ranch stay', rentals: 'Vacation rentals', camping: 'Camping and RV' };
  var AREAS = [
    { key: 'medora', label: 'In and around Medora', open: true },
    { key: 'nearby', label: 'Nearby towns and countryside', open: true },
    { key: 'dickinson', label: 'Dickinson, about 35 miles east', open: false }
  ];

  var CSS = [
    ':host{display:block;font-family:inherit;color:#25282A;line-height:1.4;--green:#1B4633;--accent:#E7805D;--accent-dark:#D07556;--line:#D8D5CC;--muted:#5A5F61;--wash:#F6F4EE}',
    '*{box-sizing:border-box}',
    '.wrap{max-width:1100px;margin:0 auto}',
    'h2{font-family:"Dharma Gothic E","Oswald","Arial Narrow",sans-serif;font-weight:700;text-transform:uppercase;letter-spacing:.02em;font-size:clamp(2rem,5vw,3rem);line-height:1;margin:0 0 .35em;color:var(--green)}',
    'h3{font-family:"Clearface",Georgia,"Times New Roman",serif;font-size:1.35rem;font-weight:700;margin:1.4em 0 .6em;color:var(--green)}',
    '.count{font-family:inherit;font-weight:400;font-size:.9rem;color:var(--muted);margin-left:.4em}',
    '.intro{margin:0 0 1em;max-width:46em}',
    '.controls{display:flex;flex-wrap:wrap;gap:14px 20px;align-items:flex-end;background:var(--wash);border:1px solid var(--line);border-radius:2px;padding:16px}',
    '.field{display:flex;flex-direction:column;gap:4px}',
    'label,.legend{font-size:.78rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--green)}',
    'input,select{font:inherit;color:inherit;background:#fff;border:1px solid #9A9C9A;border-radius:2px;padding:9px 10px;min-height:44px}',
    'input:focus-visible,select:focus-visible,button:focus-visible,a:focus-visible,summary:focus-visible{outline:3px solid var(--green);outline-offset:2px}',
    '.chips{display:flex;flex-wrap:wrap;gap:6px}',
    '.chip{font:inherit;font-size:.92rem;cursor:pointer;background:#fff;color:inherit;border:1px solid #9A9C9A;border-radius:2px;padding:9px 12px;min-height:44px}',
    '.chip[aria-pressed="true"]{background:var(--green);border-color:var(--green);color:#fff}',
    '.summary{margin:1em 0 0;font-weight:700}',
    /* cards: properties confirmed open */
    '.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:14px}',
    '.card{display:flex;flex-direction:column;border:1px solid var(--line);border-top:4px solid var(--green);border-radius:2px;background:#fff;overflow:hidden}',
    '.ph{aspect-ratio:16/9;background:var(--wash);overflow:hidden}',
    '.ph img{display:block;width:100%;height:100%;object-fit:cover}',
    '.body{display:flex;flex-direction:column;flex:1;padding:12px 14px 14px}',
    '.name{font-family:"Clearface",Georgia,"Times New Roman",serif;font-size:1.1rem;font-weight:700;line-height:1.2;margin:0 0 3px}',
    '.meta{font-size:.84rem;color:var(--muted);margin:0 0 6px}',
    '.blurb{font-size:.9rem;margin:0 0 8px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}',
    '.avail{margin:auto 0 0;padding-top:4px;font-weight:700;color:var(--green)}',
    '.avail::before{content:"";display:inline-block;width:.55em;height:.55em;border-radius:50%;background:var(--green);margin-right:.4em;vertical-align:.08em}',
    '.fine{font-size:.8rem;color:var(--muted);margin:2px 0 0}',
    '.actions{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:10px}',
    '.btn{display:inline-flex;align-items:center;justify-content:center;min-height:44px;padding:8px 18px;border-radius:2px;font-weight:700;font-size:.95rem;text-decoration:none;white-space:nowrap;border:1px solid var(--accent);background:var(--accent);color:#25282A}',
    '.btn:hover{background:var(--accent-dark);border-color:var(--accent-dark)}',
    '.tel{font-size:.9rem;color:#25282A;white-space:nowrap;text-decoration:underline;text-underline-offset:2px;padding:10px 0}',
    '.tel:hover{color:var(--green)}',
    /* rows: everything else */
    '.rows{list-style:none;margin:0;padding:0}',
    '.row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:4px 14px;align-items:center;padding:10px 0;border-top:1px solid var(--line)}',
    '.rows.pics .row{grid-template-columns:72px minmax(0,1fr) auto}',
    '.thumb{width:72px;height:54px;border-radius:2px;object-fit:cover;background:var(--wash);display:block}',
    '.row .name{font-size:1.02rem;margin:0}',
    '.row .meta{margin:2px 0 0}',
    '.go{display:flex;flex-wrap:wrap;align-items:center;justify-content:flex-end;gap:4px 14px}',
    '.btn.sm{min-height:40px;padding:6px 14px;font-size:.9rem}',
    'details{border-top:1px solid var(--line);margin-top:1.4em}',
    'details.first{border-top:0;margin-top:.6em}',
    'summary{cursor:pointer;list-style:none;padding:12px 0;font-family:"Clearface",Georgia,"Times New Roman",serif;font-size:1.2rem;font-weight:700;color:var(--green)}',
    'summary::-webkit-details-marker{display:none}',
    'summary::before{content:"+";display:inline-block;width:1.1em;font-family:inherit}',
    'details[open]>summary::before{content:"\\2212"}',
    '.closed{margin:0;padding:0;list-style:none}',
    '.closed li{padding:8px 0;border-top:1px solid var(--line)}',
    '.closed span{color:var(--muted);font-size:.88rem}',
    '.note{font-size:.82rem;color:var(--muted);margin:1.6em 0 0;max-width:60em}',
    '.msg{padding:16px;border:1px solid var(--line);background:var(--wash);border-radius:2px}',
    '@media (max-width:560px){.controls{flex-direction:column;align-items:stretch}.grid{grid-template-columns:1fr}.count{display:block;margin:2px 0 0}',
    '.row{grid-template-columns:minmax(0,1fr)}.rows.pics .row{grid-template-columns:72px minmax(0,1fr)}.go{grid-column:1/-1;justify-content:flex-start}.btn.sm{min-height:44px}}'
  ].join('\n');

  // ---------- small helpers ----------
  function h(tag, attrs, kids) {
    var el = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(function (k) {
      if (k === 'text') el.textContent = attrs[k];
      else if (k === 'class') el.className = attrs[k];
      else if (attrs[k] !== null && attrs[k] !== undefined && attrs[k] !== false) el.setAttribute(k, attrs[k]);
    });
    (kids || []).forEach(function (kid) { if (kid) el.appendChild(typeof kid === 'string' ? document.createTextNode(kid) : kid); });
    return el;
  }
  function parse(iso) { var p = iso.split('-'); return new Date(Date.UTC(+p[0], p[1] - 1, +p[2])); }
  function toIso(d) { return d.toISOString().slice(0, 10); }
  function addDays(iso, n) { var d = parse(iso); d.setUTCDate(d.getUTCDate() + n); return toIso(d); }
  function today() { var n = new Date(); return toIso(new Date(Date.UTC(n.getFullYear(), n.getMonth(), n.getDate()))); }
  function daysBetween(a, b) { return Math.round((parse(b) - parse(a)) / 86400000); }
  function nice(iso) { return parse(iso).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', timeZone: 'UTC' }); }
  function usDate(iso) { var p = iso.split('-'); return p[1] + '/' + p[2] + '/' + p[0]; }
  function plural(n, one, many) { return n + ' ' + (n === 1 ? one : many); }
  function andBits(a, b) { var out = ''; for (var i = 0; i < a.length; i++) out += (a[i] === '1' && b[i] === '1') ? '1' : '0'; return out; }

  function checkedText(iso) {
    var d = daysBetween(iso, today());
    if (d <= 0) return 'checked today';
    if (d === 1) return 'checked yesterday';
    return 'checked ' + parse(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' });
  }

  function whereText(p) {
    if (p.area === 'medora') {
      if (p.miles === 0) return 'In Medora';
      if (p.miles && p.miles < 1) return 'Under a mile from downtown Medora';
      if (p.miles) return p.town + ', ' + plural(p.miles, 'mile', 'miles') + ' from downtown';
      return p.town;
    }
    if (p.miles) return p.town + ', ' + p.miles + ' miles ' + (p.direction ? p.direction + ' of' : 'from') + ' Medora';
    return p.town;
  }

  function bookingLink(p, checkin, checkout) {
    if (p.dated_url) {
      return p.dated_url.replace('{in}', checkin).replace('{out}', checkout)
        .replace('{in_us}', usDate(checkin)).replace('{out_us}', usDate(checkout));
    }
    return p.url || null;
  }

  // The trolley is seasonal, so it is mentioned only when every night of the stay falls in its season.
  function trolleyRuns(checkin, nights) {
    var months = (DATA && DATA.trolley_months) || [];
    if (!months.length) return false;
    for (var i = 0; i < nights; i++) {
      if (months.indexOf(parse(addDays(checkin, i)).getUTCMonth() + 1) < 0) return false;
    }
    return true;
  }

  // ---------- availability ----------
  function evaluate(p, data, checkin, nights) {
    if (!p.live) return { status: 'link' };
    var oldest = null, now = today(), mask = null, grouped = false, of = null;
    for (var i = 0; i < nights; i++) {
      var rec = (data.nights[addDays(checkin, i)] || {})[p.id];
      if (!rec || !rec.t || daysBetween(rec.t, now) > STALE_DAYS) return { status: 'unknown' };
      if (rec.a !== 1) return { status: 'unavailable' };
      if (!oldest || rec.t < oldest) oldest = rec.t;
      if (rec.u) {
        // One character per cabin or rental. A unit counts only if it is open every night of the stay.
        grouped = true;
        of = rec.of || rec.u.length;
        mask = mask === null ? rec.u : (mask.length === rec.u.length ? andBits(mask, rec.u) : '');
      }
    }
    if (grouped) {
      var count = (mask.match(/1/g) || []).length;
      if (!count) return { status: 'unavailable' };
      return { status: 'available', checked: oldest, count: count, of: of };
    }
    return { status: 'available', checked: oldest };
  }

  // ---------- rendering ----------
  var state = { checkin: addDays(today(), 14), nights: 1, type: 'all' };
  var DATA = null, PHOTOS = {};
  var results = h('div', { 'aria-live': 'polite' });

  function matchesType(p) {
    if (state.type === 'all') return true;
    if (state.type === 'cabin') return p.type === 'cabin' || p.type === 'rentals';
    return p.type === state.type;
  }

  function photo(p, cls) {
    var ph = PHOTOS[p.id];
    if (!ph || !ph.src || opts.photos === 'off') return null;
    var img = h('img', { class: cls, src: ph.src, alt: '', loading: 'lazy', decoding: 'async', referrerpolicy: 'no-referrer' });
    return img;
  }

  function metaText(p, trolley, withSeason) {
    var parts = [TYPE_NAME[p.type], whereText(p)];
    if (withSeason && p.season) parts.push(p.season);
    if (trolley && p.trolley) parts.push('Free summer trolley stop');
    return parts.join(' · ');
  }

  function actionLinks(p, live, checkin, checkout, small) {
    var link = bookingLink(p, checkin, checkout), out = [];
    var label = p.type === 'rentals' ? 'See rentals' : (live ? 'Book' : (p.dated_url ? 'Check dates' : 'Website'));
    var tel = p.phone ? 'tel:+1' + p.phone.replace(/\D/g, '').replace(/^1/, '') : null;
    if (link) {
      out.push(h('a', { class: 'btn' + (small ? ' sm' : ''), href: link, target: '_blank', rel: 'noopener',
        'aria-label': label + ': ' + p.name + ' (opens in a new tab)', text: label }));
      if (tel) out.push(h('a', { class: 'tel', href: tel, 'aria-label': 'Call ' + p.name + ' at ' + p.phone, text: p.phone }));
    } else if (tel) {
      out.push(h('a', { class: 'btn' + (small ? ' sm' : ''), href: tel, 'aria-label': 'Call ' + p.name + ' at ' + p.phone, text: 'Call ' + p.phone }));
    }
    return out;
  }

  // A card: used only for places confirmed open for the dates.
  function card(p, ev, checkin, checkout, trolley) {
    var headline = p.type === 'camping' ? 'Sites available' : 'Rooms available';
    var fine = checkedText(ev.checked);
    fine = fine.charAt(0).toUpperCase() + fine.slice(1);
    if (ev.count) {
      headline = plural(ev.count, p.type === 'rentals' ? 'rental' : 'unit', p.type === 'rentals' ? 'rentals' : 'units') + ' available';
      fine += ' · ' + ev.count + ' of ' + ev.of + ' tracked' + (p.type === 'rentals' ? '; more may be listed' : '');
    }
    var img = photo(p, '');
    var frame = img ? h('div', { class: 'ph' }, [img]) : null;
    if (img) img.addEventListener('error', function () { if (frame.parentNode) frame.parentNode.removeChild(frame); });
    return h('article', { class: 'card' }, [
      frame,
      h('div', { class: 'body' }, [
        h('p', { class: 'name', text: p.name }),
        h('p', { class: 'meta', text: metaText(p, trolley, false) }),
        p.blurb ? h('p', { class: 'blurb', text: p.blurb }) : null,
        h('p', { class: 'avail', text: headline }),
        h('p', { class: 'fine', text: fine }),
        h('div', { class: 'actions' }, actionLinks(p, true, checkin, checkout, false))
      ])
    ]);
  }

  // A row: used for places to check directly. One line each on a wide screen.
  function row(p, checkin, checkout, trolley) {
    var slot = null;
    if (opts.photos === 'all') {
      var img = photo(p, 'thumb');
      slot = img || h('span', { class: 'thumb' });
      if (img) img.addEventListener('error', function () { img.style.visibility = 'hidden'; });
    }
    return h('li', { class: 'row' }, [
      slot,
      h('div', null, [h('p', { class: 'name', text: p.name }), h('p', { class: 'meta', text: metaText(p, trolley, true) })]),
      h('div', { class: 'go' }, actionLinks(p, false, checkin, checkout, true))
    ]);
  }

  function render() {
    results.textContent = '';
    if (!DATA) return;
    var checkin = state.checkin, checkout = addDays(checkin, state.nights);
    var trolley = trolleyRuns(checkin, state.nights);
    var props = DATA.properties.filter(function (p) { return matchesType(p) && (!opts.area || p.area === opts.area); });
    var open = [], closed = [], other = [];
    props.forEach(function (p) {
      var ev = evaluate(p, DATA, checkin, state.nights);
      if (ev.status === 'available') open.push({ p: p, ev: ev });
      else if (ev.status === 'unavailable') closed.push(p);
      else other.push(p);
    });

    results.appendChild(h('p', { class: 'summary', text: nice(checkin) + ' to ' + nice(checkout) + ', ' + plural(state.nights, 'night', 'nights') }));

    // Dickinson is a 35-mile drive, so its open hotels sit in their own fold below the nearer ones.
    var openNear = open.filter(function (o) { return o.p.area !== 'dickinson'; });
    var openFar = open.filter(function (o) { return o.p.area === 'dickinson'; });
    function cards(list) { return h('div', { class: 'grid' }, list.map(function (o) { return card(o.p, o.ev, checkin, checkout, trolley); })); }
    if (open.length) {
      results.appendChild(h('h3', null, ['Open for your dates', h('span', { class: 'count', text: plural(open.length, 'place', 'places') + ' with rooms or sites when last checked' })]));
      if (openNear.length) results.appendChild(cards(openNear));
      if (openFar.length) {
        results.appendChild(h('details', openNear.length ? { class: 'first' } : { class: 'first', open: '' }, [
          h('summary', null, ['Dickinson, about 35 miles east', h('span', { class: 'count', text: plural(openFar.length, 'hotel', 'hotels') + ' showing rooms' })]),
          cards(openFar)
        ]));
      }
    }

    AREAS.forEach(function (area) {
      var list = other.filter(function (p) { return p.area === area.key; });
      if (!list.length) return;
      results.appendChild(h('details', area.open || !open.length ? { open: '' } : null, [
        h('summary', null, [area.label, h('span', { class: 'count', text: plural(list.length, 'place', 'places') + ' to check directly' })]),
        h('ul', { class: opts.photos === 'all' ? 'rows pics' : 'rows' }, list.map(function (p) { return row(p, checkin, checkout, trolley); }))
      ]));
    });

    if (closed.length) {
      results.appendChild(h('details', null, [
        h('summary', null, ['Full or closed on these dates', h('span', { class: 'count', text: plural(closed.length, 'place', 'places') })]),
        h('ul', { class: 'closed' }, closed.map(function (p) {
          return h('li', null, [p.name, ' ', h('span', { text: '· ' + p.season })]);
        }))
      ]));
    }

    if (!open.length && !other.length && !closed.length) {
      results.appendChild(h('p', { class: 'msg', text: 'Nothing matches that filter. Try All.' }));
    }
    results.appendChild(h('p', { class: 'note', text:
      'Availability is checked for two adults and changes quickly, so the booking site has the final word on rooms and rates. ' +
      'Lodging listed here is run by independent businesses, not by the Library. Photos are shown from each property’s own website.' }));
  }

  function controls() {
    var min = today();
    var date = h('input', { type: 'date', id: 'ci', value: state.checkin, min: min, max: addDays(min, (DATA && DATA.horizon_nights) || 330) });
    date.addEventListener('change', function () { if (date.value && date.value >= min) { state.checkin = date.value; render(); } });
    var nights = h('select', { id: 'nt' });
    for (var i = 1; i <= MAX_NIGHTS; i++) nights.appendChild(h('option', { value: i, text: plural(i, 'night', 'nights') }));
    nights.addEventListener('change', function () { state.nights = +nights.value; render(); });
    var chips = TYPES.map(function (t) {
      var b = h('button', { type: 'button', class: 'chip', 'aria-pressed': String(t.key === state.type), text: t.label });
      b.addEventListener('click', function () {
        state.type = t.key;
        chips.forEach(function (c, j) { c.setAttribute('aria-pressed', String(TYPES[j].key === t.key)); });
        render();
      });
      return b;
    });
    return h('div', { class: 'controls' }, [
      h('div', { class: 'field' }, [h('label', { for: 'ci', text: 'Check-in' }), date]),
      h('div', { class: 'field' }, [h('label', { for: 'nt', text: 'Stay' }), nights]),
      h('div', { class: 'field', role: 'group', 'aria-label': 'Type of lodging' }, [h('span', { class: 'legend', text: 'Show' }), h('div', { class: 'chips' }, chips)])
    ]);
  }

  var wrap = h('div', { class: 'wrap' });
  root.appendChild(h('style', { text: CSS }));
  root.appendChild(wrap);
  if (opts.heading !== 'off') {
    wrap.appendChild(h('h2', { text: 'Find a place to stay' }));
    wrap.appendChild(h('p', { class: 'intro', text: 'Pick your dates to see which Medora hotels, cabins and campgrounds have room, then book directly with the property.' }));
  }
  var loading = h('p', { class: 'msg', text: 'Loading places to stay…' });
  wrap.appendChild(loading);

  function getJson(path) {
    return fetch(BASE + path, { cache: 'no-cache' }).then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); });
  }

  Promise.all([
    getJson('data/availability.json'),
    getJson('data/photos.json').catch(function () { return {}; })   // photos are optional
  ]).then(function (res) {
    DATA = res[0];
    DATA.nights = DATA.nights || {};
    PHOTOS = (res[1] && res[1].photos) || {};
    wrap.removeChild(loading);
    wrap.appendChild(controls());
    wrap.appendChild(results);
    render();
  }).catch(function () {
    loading.textContent = '';
    loading.appendChild(document.createTextNode('The lodging finder could not load. '));
    loading.appendChild(h('a', { href: 'https://www.trlibrary.com/visit/lodging', text: 'See the full list of places to stay.' }));
  });
})();
