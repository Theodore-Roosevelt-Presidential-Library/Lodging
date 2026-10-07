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
 *   data-url="on"            keep the chosen dates, tab and filter in the page address, so the view can be shared
 *   data-fonts="off"         do not load the brand fonts (they are loaded from trlibrary.com on any other site)
 *   data-sticky-top="94"     pixels to leave above the pinned tab bar (default: measured from the page's own fixed header)
 *
 * The page address can open the finder on a particular view (all optional):
 *   ?checkin=2027-06-18&nights=2&tab=rentals&type=cabin&place=hotel-1883
 *   tab: medora | rentals | nearby | dickinson     type: all | hotel | cabin | camping
 *   place: a property id from data/properties.json; its card is brought into view and outlined
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

  var STALE_DAYS = 10;        // an answer older than this is not shown...
  var STALE_DAYS_FAR = 16;    // ...except for nights more than two months out, which change slowly
  var FAR_NIGHTS = 60;
  var MAX_NIGHTS = 7;
  var TYPES = [
    { key: 'all', label: 'All' },
    { key: 'hotel', label: 'Hotels and inns' },
    { key: 'cabin', label: 'Cabins and rentals' },
    { key: 'camping', label: 'Camping and RV' }
  ];
  var TYPE_NAME = { hotel: 'Hotel or inn', cabin: 'Cabin or ranch stay', rentals: 'Vacation rentals', camping: 'Camping and RV' };
  // One tab per group of places. Only one group shows at a time, so nothing needs a long scroll.
  var TABS = [
    { key: 'medora', label: 'Medora', intro: 'Hotels, cabins and campgrounds in and around Medora.',
      has: function (p) { return p.type !== 'rentals' && p.area === 'medora'; } },
    { key: 'rentals', label: 'Vacation rentals', intro: 'Private homes and cabins around Medora, listed by their hosts on Airbnb and Vrbo.',
      has: function (p) { return p.type === 'rentals'; } },
    { key: 'nearby', label: 'Nearby towns', intro: 'Towns and countryside within about 45 miles of Medora.',
      has: function (p) { return p.type !== 'rentals' && p.area === 'nearby'; } },
    { key: 'dickinson', label: 'Dickinson', intro: 'About 35 miles east of Medora on Interstate 94.',
      has: function (p) { return p.type !== 'rentals' && p.area === 'dickinson'; } }
  ];
  var SECTIONS = [
    { key: 'open', label: 'Open for your dates' },
    { key: 'check', label: 'Check directly' },
    { key: 'more', label: 'Search more rentals' },
    { key: 'closed', label: 'Full or closed on these dates' }
  ];
  var SITE = { airbnb: 'Airbnb', vrbo: 'Vrbo' };
  var ICONS = {
    hotel: 'M3 19v-8h18v8M3 15h18M6 11V7h5v4M3 19v1.5M21 19v1.5',
    cabin: 'M3.5 11.5 12 5l8.5 6.5M6 10v9h12v-9M10 19v-5h4v5',
    rentals: 'M3.5 11.5 12 5l8.5 6.5M6 10v9h12v-9M10 19v-5h4v5',
    camping: 'M2.5 19 12 5l9.5 14zM12 5v14M9 19l3-5 3 5'
  };

  // Brand fonts, served by trlibrary.com. Font faces have to be declared on the page itself, not inside the widget.
  var FONT_BASE = 'https://www.trlibrary.com/themes/custom/trpl/css/';
  var FONTS = [
    ['Dharma Gothic E', 700, 'dharma_type-dharmagothice-bold.woff2'],
    ['Clearface', 400, 'clearfacestd-regular.woff2'],
    ['Clearface', 700, 'clearfacestd-heavy.woff2'],
    ['Frutiger', 400, 'frutigerltstd-regular.woff2'],
    ['Frutiger', 700, 'frutigerltstd-bold.woff2']
  ];
  (function loadFonts() {
    var onMainSite = /^(www\.)?trlibrary\.com$/.test(location.hostname);   // already has them
    if (opts.fonts === 'off' || onMainSite || document.getElementById('trpl-brand-fonts')) return;
    var style = document.createElement('style');
    style.id = 'trpl-brand-fonts';
    style.textContent = FONTS.map(function (f) {
      return '@font-face{font-family:"' + f[0] + '";font-weight:' + f[1] + ';font-style:normal;font-display:swap;src:url("' + FONT_BASE + f[2] + '") format("woff2")}';
    }).join('');
    document.head.appendChild(style);
  })();
  var SANS = 'Frutiger,"Frutiger Next","Helvetica Neue",Arial,sans-serif';
  var SERIF = 'Clearface,Georgia,"Times New Roman",serif';

  // The arrow on the nights menu, drawn here so the menu looks the same in every browser.
  var CHEVRON = "url(\"data:image/svg+xml;utf8,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 12 8'%3E%3Cpath d='M1 1.5l5 5 5-5' fill='none' stroke='%231B4633' stroke-width='2'/%3E%3C/svg%3E\")";

  var CSS = [
    ':host{display:block;font-family:' + SANS + ';color:#25282A;line-height:1.4;--green:#1B4633;--accent:#E7805D;--accent-dark:#D07556;--line:#D8D5CC;--muted:#5A5F61;--wash:#F6F4EE;--bg:#fff;--top:0px}',
    '*{box-sizing:border-box}',
    '.wrap{max-width:1100px;margin:0 auto}',
    'h2{font-family:"Dharma Gothic E","Oswald","Arial Narrow",sans-serif;font-weight:700;text-transform:uppercase;letter-spacing:.02em;font-size:clamp(2rem,5vw,3rem);line-height:1;margin:0 0 .35em;color:var(--green)}',
    'h3{font-size:.95rem;font-weight:700;text-transform:uppercase;letter-spacing:.05em;margin:1.7em 0 .7em;color:var(--green)}',
    '.count{font-weight:400;font-size:.86rem;text-transform:none;letter-spacing:0;color:var(--muted);margin-left:.6em}',
    '.intro{font-family:' + SERIF + ';font-size:1.1rem;margin:0 0 1em;max-width:46em}',
    '.controls{display:flex;flex-wrap:wrap;gap:14px 20px;align-items:flex-end;background:var(--wash);border:1px solid var(--line);border-radius:2px;padding:16px}',
    '.field{display:flex;flex-direction:column;gap:6px;min-width:0}',
    'label,.legend{display:block;font-size:.78rem;line-height:1;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--green)}',
    /* Every control is the same 44px box, with the browser's own styling switched off, so the row lines up everywhere. */
    'input,select{-webkit-appearance:none;-moz-appearance:none;appearance:none;display:block;box-sizing:border-box;height:44px;margin:0;padding:0 12px;font:inherit;font-size:1rem;line-height:normal;color:#25282A;background-color:#fff;border:1px solid #9A9C9A;border-radius:2px}',
    'input[type=date]{min-width:9.6em}',
    'input::-webkit-date-and-time-value{text-align:left;line-height:42px}',
    'input::-webkit-datetime-edit{padding:0;line-height:42px}',
    'select{padding-right:38px;cursor:pointer;background-image:' + CHEVRON + ';background-repeat:no-repeat;background-position:right 13px center;background-size:12px 8px}',
    'input:hover,select:hover,.chip:hover{border-color:#25282A}',
    'input:focus-visible,select:focus-visible,button:focus-visible,a:focus-visible{outline:3px solid var(--green);outline-offset:2px}',
    '.chips{display:flex;flex-wrap:wrap;gap:6px}',
    '.chip{-webkit-appearance:none;appearance:none;box-sizing:border-box;height:44px;margin:0;padding:0 14px;font:inherit;font-size:1rem;line-height:normal;cursor:pointer;background:#fff;color:#25282A;border:1px solid #9A9C9A;border-radius:2px}',
    '.chip[aria-pressed="true"],.chip[aria-pressed="true"]:hover{background:var(--green);border-color:var(--green);color:#fff}',
    /* the pinned tab bar */
    '.bar{position:sticky;top:var(--top);z-index:5;display:flex;align-items:flex-end;justify-content:space-between;gap:8px 20px;margin-top:14px;background:var(--bg);border-bottom:1px solid var(--line)}',
    '.bar.stuck{box-shadow:0 6px 8px -6px rgba(37,40,42,.25)}',
    '.tabs{display:flex;gap:2px;overflow-x:auto;scrollbar-width:none;-ms-overflow-style:none;min-width:0}',
    '.tabs::-webkit-scrollbar{display:none}',
    '.tab{font:inherit;font-weight:700;font-size:.98rem;white-space:nowrap;cursor:pointer;background:none;color:var(--muted);border:0;border-bottom:4px solid transparent;border-radius:0;padding:12px 14px 9px;min-height:48px;display:inline-flex;align-items:center;gap:8px;margin-bottom:-1px}',
    '.tab:hover{color:var(--green)}',
    '.tab[aria-selected="true"]{color:var(--green);border-bottom-color:var(--accent)}',
    '.tab:focus-visible{outline-offset:-3px}',
    '.pill{font-weight:700;font-size:.74rem;line-height:1;padding:4px 7px;border-radius:999px;background:var(--green);color:#fff}',
    '.pill.none{background:var(--wash);color:var(--muted);font-weight:400}',
    '.when{margin:0;padding:0 2px 12px;font-size:.88rem;font-weight:700;white-space:nowrap}',
    '.panel{scroll-margin-top:calc(var(--top) + 64px)}',
    '.panel:focus{outline:none}',
    '.lede{font-family:' + SERIF + ';margin:14px 0 0;color:var(--muted);font-size:1rem}',
    /* cards */
    '.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:14px}',
    '.grid+.grid{margin-top:14px}',
    '.card{display:flex;flex-direction:column;border:1px solid var(--line);border-top:4px solid var(--line);border-radius:2px;background:#fff;overflow:hidden}',
    '.card.open{border-top-color:var(--green)}',
    '.card.hit{outline:3px solid var(--accent);outline-offset:3px;scroll-margin-top:calc(var(--top) + 80px)}',
    '.ph{aspect-ratio:16/9;background:var(--wash);overflow:hidden;display:flex;align-items:center;justify-content:center}',
    '.ph img{display:block;width:100%;height:100%;object-fit:cover}',
    '.ph svg{width:44px;height:44px;stroke:#B9B5A8;fill:none;stroke-width:1.2;stroke-linecap:round;stroke-linejoin:round}',
    '.card.closed .ph img{filter:grayscale(1);opacity:.75}',
    '.body{display:flex;flex-direction:column;flex:1;padding:12px 14px 14px}',
    '.name{font-family:' + SERIF + ';font-size:1.15rem;font-weight:700;line-height:1.2;margin:0 0 3px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}',
    '.meta{font-size:.84rem;color:var(--muted);margin:0 0 6px}',
    '.blurb{font-family:' + SERIF + ';font-size:.98rem;line-height:1.35;margin:0 0 8px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}',
    '.avail{margin:auto 0 0;padding-top:4px;font-weight:700;color:var(--green)}',
    '.avail::before{content:"";display:inline-block;width:.55em;height:.55em;border-radius:50%;background:var(--green);border:2px solid var(--green);margin-right:.4em;vertical-align:.02em}',
    '.check .avail,.more .avail{color:#25282A}',
    '.check .avail::before,.more .avail::before{background:transparent;border-color:#8A8D8B}',
    '.closed .avail{color:var(--muted)}',
    '.closed .avail::before{background:#8A8D8B;border-color:#8A8D8B}',
    '.fine{font-size:.8rem;color:var(--muted);margin:2px 0 0}',
    '.actions{display:flex;align-items:center;gap:8px 10px;margin-top:10px}',
    '.btn{display:inline-flex;align-items:center;justify-content:center;min-height:44px;padding:8px 18px;border-radius:2px;font-weight:700;font-size:.95rem;text-decoration:none;white-space:nowrap;border:1px solid var(--accent);background:var(--accent);color:#25282A}',
    '.btn:hover{background:var(--accent-dark);border-color:var(--accent-dark)}',
    '.btn.quiet{background:#fff;border-color:#8A8D8B}',
    '.btn.quiet:hover{background:var(--wash);border-color:#25282A}',
    '.tel{margin-left:auto;font-size:.9rem;color:#25282A;white-space:nowrap;text-decoration:underline;text-underline-offset:2px;padding:10px 0}',
    '.tel:hover{color:var(--green)}',
    '.note{font-size:.82rem;color:var(--muted);margin:1.8em 0 0;max-width:60em}',
    '.msg{padding:16px;border:1px solid var(--line);background:var(--wash);border-radius:2px}',
    '@media (max-width:760px){.bar{flex-direction:column-reverse;align-items:stretch;gap:0}.when{padding:10px 2px 0;font-size:.84rem}}',
    '@media (max-width:560px){.controls{flex-direction:column;align-items:stretch}.grid{grid-template-columns:1fr}.count{display:block;margin:2px 0 0}.tab{padding:12px 11px 9px;font-size:.93rem}}'
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
  function cap(s) { return s.charAt(0).toUpperCase() + s.slice(1); }

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

  // A single Airbnb or Vrbo listing, opened on the chosen dates.
  function unitLink(unit, checkin, checkout) {
    if (!unit.url) return null;
    var q = unit.src === 'airbnb'
      ? 'check_in=' + checkin + '&check_out=' + checkout + '&adults=2'
      : 'chkin=' + checkin + '&chkout=' + checkout + '&startDate=' + checkin + '&endDate=' + checkout + '&adults=2';
    return unit.url + (unit.url.indexOf('?') < 0 ? '?' : '&') + q;
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
  function tooOld(rec, night, now) {
    var limit = daysBetween(now, night) > FAR_NIGHTS ? STALE_DAYS_FAR : STALE_DAYS;
    return !rec || !rec.t || daysBetween(rec.t, now) > limit;
  }
  function evaluate(p, data, checkin, nights) {
    if (!p.live) return { status: 'link' };
    var oldest = null, now = today(), mask = null, grouped = false, of = null;
    for (var i = 0; i < nights; i++) {
      var night = addDays(checkin, i), rec = (data.nights[night] || {})[p.id];
      if (tooOld(rec, night, now)) return { status: 'unknown' };
      if (!oldest || rec.t < oldest) oldest = rec.t;
      if (rec.a !== 1) return { status: 'unavailable', checked: oldest, of: rec.u ? (rec.of || rec.u.length) : null };
      if (rec.u) {
        // One character per cabin or rental. A unit counts only if it is open every night of the stay.
        grouped = true;
        of = rec.of || rec.u.length;
        mask = mask === null ? rec.u : (mask.length === rec.u.length ? andBits(mask, rec.u) : '');
      }
    }
    if (grouped) {
      var count = (mask.match(/1/g) || []).length;
      if (!count) return { status: 'unavailable', checked: oldest, of: of };
      return { status: 'available', checked: oldest, count: count, of: of };
    }
    return { status: 'available', checked: oldest };
  }

  // For a property whose listings are shown one by one: which of them are open for the whole stay.
  function unitMask(p, units, data, checkin, nights) {
    var mask = null, oldest = null, now = today();
    for (var i = 0; i < nights; i++) {
      var night = addDays(checkin, i), rec = (data.nights[night] || {})[p.id];
      if (tooOld(rec, night, now) || !rec.u || rec.u.length !== units.length) return null;
      mask = mask === null ? rec.u : andBits(mask, rec.u);
      if (!oldest || rec.t < oldest) oldest = rec.t;
    }
    return { mask: mask, checked: oldest };
  }

  function nameKey(name) { return String(name).toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim(); }

  // A property whose cabins are listed on Airbnb or Vrbo can take its availability from those listings
  // ("units_from" in the property list). A cabin listed on both sites under one name counts once.
  function borrowed(p, checkin, nights) {
    var seen = {}, checked = null;
    Object.keys(p.units_from || {}).forEach(function (gid) {
      var units = DATA.units && DATA.units[gid], group = BY_ID[gid];
      var um = units && group ? unitMask(group, units, DATA, checkin, nights) : null;
      if (!um) return;
      p.units_from[gid].forEach(function (id) {
        var i = 0;
        while (i < units.length && String(units[i].id) !== String(id)) i++;
        if (i === units.length) return;
        var extra = LISTINGS[units[i].src + ':' + units[i].id] || {};
        var key = nameKey(units[i].name || extra.name || gid + ' ' + id);
        seen[key] = seen[key] || um.mask[i] === '1';
        if (!checked || um.checked < checked) checked = um.checked;
      });
    });
    var keys = Object.keys(seen);
    return keys.length ? { open: keys.filter(function (k) { return seen[k]; }).length, total: keys.length, checked: checked } : null;
  }

  // Availability for one property card, counting any borrowed listings. When only some of a property's
  // units are tracked and those are all booked, the answer is "check directly", not "full".
  function status(p, checkin) {
    var ev = evaluate(p, DATA, checkin, state.nights);
    var b = p.units_from ? borrowed(p, checkin, state.nights) : null;
    if (b) {
      var known = ev.status === 'available' || ev.status === 'unavailable';
      var open = (ev.status === 'available' ? ev.count || 0 : 0) + b.open;
      var total = (known ? ev.of || 0 : 0) + b.total;
      var checked = known && ev.checked && ev.checked < b.checked ? ev.checked : b.checked;
      ev = open ? { status: 'available', checked: checked, count: open, of: total } : { status: 'unavailable', checked: checked, of: total };
    }
    if (ev.status === 'unavailable' && ev.of && p.units && ev.of < p.units) return { status: 'unknown' };
    return ev;
  }

  // ---------- cards ----------
  var state = { checkin: addDays(today(), 14), nights: 1, type: 'all', tab: null, place: null };
  var PARAMS = ['checkin', 'nights', 'tab', 'type', 'place'];

  // Open on the view named in the page address, if any.
  (function readAddress() {
    var q;
    try { q = new URLSearchParams(location.search); } catch (e) { return; }
    var ci = q.get('checkin'), n = parseInt(q.get('nights'), 10), type = q.get('type'), tab = q.get('tab');
    if (/^\d{4}-\d{2}-\d{2}$/.test(ci || '') && !isNaN(parse(ci)) && ci >= today()) state.checkin = ci;
    if (n >= 1 && n <= MAX_NIGHTS) state.nights = n;
    if (TYPES.some(function (t) { return t.key === type; })) state.type = type;
    if (TABS.some(function (t) { return t.key === tab; })) state.tab = tab;
    state.place = q.get('place') || null;
  })();

  function writeAddress() {
    if (opts.url !== 'on' || !window.history || !history.replaceState) return;
    try {
      var q = new URLSearchParams(location.search);
      PARAMS.forEach(function (k) { q.delete(k); });
      q.set('checkin', state.checkin);
      q.set('nights', state.nights);
      if (state.tab) q.set('tab', state.tab);
      if (state.type !== 'all') q.set('type', state.type);
      if (state.place) q.set('place', state.place);
      history.replaceState(null, '', location.pathname + '?' + q.toString() + location.hash);
    } catch (e) { /* the address is a convenience; the finder works without it */ }
  }
  var DATA = null, PHOTOS = {}, LISTINGS = {}, BY_ID = {};

  function matchesType(p) {
    if (state.type === 'all') return true;
    if (state.type === 'cabin') return p.type === 'cabin' || p.type === 'rentals';
    return p.type === state.type;
  }

  function telLink(p) {
    return p.phone ? { tel: true, href: 'tel:+1' + p.phone.replace(/\D/g, '').replace(/^1/, ''), label: p.phone, aria: 'Call ' + p.name + ' at ' + p.phone } : null;
  }

  // Each of these returns a plain description of one card; draw() turns it into elements.
  function propCard(p, ev, checkin, checkout, trolley) {
    var link = bookingLink(p, checkin, checkout), tel = telLink(p);
    var meta = [TYPE_NAME[p.type], whereText(p)];
    if (trolley && p.trolley) meta.push('Free summer trolley stop');
    var c = { id: p.id, prop: p.id, type: p.type, name: p.name, meta: meta.join(' · '), blurb: p.blurb, photo: (PHOTOS[p.id] || {}).src, actions: [] };
    var label;
    if (ev.status === 'available') {
      c.section = 'open';
      c.headline = p.type === 'camping' ? 'Sites available' : 'Rooms available';
      c.fine = cap(checkedText(ev.checked));
      if (ev.count) {
        c.headline = plural(ev.count, p.type === 'rentals' ? 'rental' : 'unit', p.type === 'rentals' ? 'rentals' : 'units') + ' available';
        c.fine += ' · ' + ev.count + ' of ' + ev.of + ' tracked' + (p.type === 'rentals' ? '; more may be listed' : '');
      }
      label = p.type === 'rentals' ? 'See rentals' : 'Book';
    } else if (ev.status === 'unavailable') {
      c.section = 'closed';
      c.headline = 'Full or closed';
      c.fine = [p.season, ev.checked ? cap(checkedText(ev.checked)) : null].filter(Boolean).join(' · ');
      label = p.type === 'rentals' ? 'See rentals' : 'Website';
      c.quiet = true;
    } else {
      c.section = 'check';
      c.headline = p.first_come ? 'First come, first served' : (link ? 'Check dates directly' : 'Call to check dates');
      c.fine = p.season || '';
      label = p.type === 'rentals' ? 'See rentals' : (p.dated_url && !p.first_come ? 'Check dates' : 'Website');
    }
    if (link) {
      c.actions.push({ href: link, label: label, aria: label + ': ' + p.name + ' (opens in a new tab)' });
      if (tel) c.actions.push(tel);
    } else if (tel) {
      c.actions.push({ href: tel.href, label: 'Call ' + p.phone, aria: tel.aria, same: true });
    }
    return c;
  }

  function unitCard(p, unit, open, checked, checkin, checkout) {
    var site = SITE[unit.src] || 'the listing site';
    var c = { id: p.id + ':' + unit.id, prop: p.id, type: 'rentals', name: unit.name, meta: 'Vacation rental · Listed on ' + site, blurb: unit.summary || unit.facts,
      photo: unit.photo, fine: cap(checkedText(checked)), actions: [], site: site, sites: [site], isOpen: open,
      twin: nameKey(unit.name) };
    c.section = open ? 'open' : 'closed';
    c.headline = open ? 'Available' : 'Booked on these dates';
    c.quiet = !open;
    var link = open ? unitLink(unit, checkin, checkout) : unit.url;
    if (link) c.actions.push({ href: link, label: 'View on ' + site, aria: 'View ' + unit.name + ' on ' + site + ' (opens in a new tab)' });
    return c;
  }

  // The Airbnb or Vrbo search itself, offered beside the individual listings.
  function searchCard(p, shown, extraOpen, checkin, checkout) {
    var link = bookingLink(p, checkin, checkout);
    var c = { id: shown ? null : p.id, prop: p.id, section: 'more', type: 'rentals', name: p.name, meta: TYPE_NAME.rentals + ' · ' + whereText(p), blurb: p.blurb, actions: [] };
    c.headline = extraOpen ? plural(extraOpen, 'more rental', 'more rentals') + ' available' : 'More may be listed';
    c.fine = plural(shown, 'listing is', 'listings are') + ' tracked here.';
    if (link) c.actions.push({ href: link, label: 'See rentals', aria: 'See rentals: ' + p.name + ' (opens in a new tab)' });
    return c;
  }

  function buildCards(p, checkin, checkout, trolley) {
    var units = p.list_units && DATA.units && DATA.units[p.id];
    var um = units && units.length ? unitMask(p, units, DATA, checkin, state.nights) : null;
    if (!um) return [propCard(p, status(p, checkin), checkin, checkout, trolley)];
    var out = [], shown = 0, extraOpen = 0;
    units.forEach(function (raw, i) {
      var extra = LISTINGS[raw.src + ':' + raw.id] || {};
      if (extra.hidden) return;
      var unit = { id: raw.id, src: raw.src, url: raw.url, name: raw.name || extra.name, photo: raw.photo || extra.src,
        summary: extra.summary, facts: raw.facts };
      var open = um.mask[i] === '1';
      if (!unit.name) { if (open) extraOpen++; return; }
      shown++;
      out.push(unitCard(p, unit, open, um.checked, checkin, checkout));
    });
    out.push(searchCard(p, shown, extraOpen, checkin, checkout));
    return out;
  }

  // A rental listed on both Airbnb and Vrbo under the same name becomes one card with a button for each.
  function mergeTwins(cards) {
    var seen = {}, out = [];
    cards.forEach(function (c) {
      var first = c.twin && seen[c.twin];
      if (!first || first.sites.indexOf(c.site) >= 0) {
        if (c.twin) seen[c.twin] = c;
        out.push(c);
        return;
      }
      var both = first.isOpen === c.isOpen;
      if (c.isOpen && !first.isOpen) {           // open on one site only: show that one
        first.section = c.section; first.headline = c.headline; first.quiet = c.quiet; first.isOpen = true;
        first.actions = c.actions;
      } else if (both) {
        first.actions = first.actions.concat(c.actions).map(function (a, i) {
          return { href: a.href, label: i ? c.site : first.sites[0], aria: a.aria };
        });
      }
      first.sites.push(c.site);
      first.meta = 'Vacation rental · Listed on ' + first.sites.join(' and ');
      first.photo = first.photo || c.photo;
      first.blurb = first.blurb || c.blurb;
    });
    return out;
  }

  function frame(c) {
    var box = h('div', { class: 'ph' });
    function icon() {
      box.textContent = '';
      box.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="' + (ICONS[c.type] || ICONS.hotel) + '"/></svg>';
    }
    if (c.photo) {
      var img = h('img', { src: c.photo, alt: '', loading: 'lazy', decoding: 'async', referrerpolicy: 'no-referrer' });
      img.addEventListener('error', icon);
      box.appendChild(img);
    } else icon();
    return box;
  }

  function draw(c, withFrame) {
    return h('article', { class: 'card ' + c.section + (state.place && c.id === state.place ? ' hit' : ''), 'data-id': c.id || null }, [
      withFrame ? frame(c) : null,
      h('div', { class: 'body' }, [
        h('p', { class: 'name', text: c.name }),
        h('p', { class: 'meta', text: c.meta }),
        c.blurb ? h('p', { class: 'blurb', text: c.blurb }) : null,
        h('p', { class: 'avail', text: c.headline }),
        c.fine ? h('p', { class: 'fine', text: c.fine }) : null,
        c.actions.length ? h('div', { class: 'actions' }, c.actions.map(function (a) {
          if (a.tel) return h('a', { class: 'tel', href: a.href, 'aria-label': a.aria, text: a.label });
          return h('a', { class: 'btn' + (c.quiet ? ' quiet' : ''), href: a.href, target: a.same ? null : '_blank', rel: a.same ? null : 'noopener', 'aria-label': a.aria, text: a.label });
        })) : null
      ])
    ]);
  }

  // ---------- page ----------
  var sentinel = h('div', { 'aria-hidden': 'true' });
  var tablist = h('div', { class: 'tabs', role: 'tablist', 'aria-label': 'Places to stay, by area' });
  var when = h('p', { class: 'when', 'aria-live': 'polite' });
  var bar = h('div', { class: 'bar' }, [tablist, when]);
  var panel = h('div', { class: 'panel', role: 'tabpanel', tabindex: '-1' });
  var note = h('p', { class: 'note', text:
    'Availability is checked for two adults and changes quickly, so the booking site has the final word on rooms and rates. ' +
    'Lodging listed here, including rentals on Airbnb and Vrbo, is run by independent businesses and hosts, not by the Library. ' +
    'Photos come from each property’s website or its public listing.' });
  var model = [];

  function compute() {
    var checkin = state.checkin, checkout = addDays(checkin, state.nights), trolley = trolleyRuns(checkin, state.nights);
    var props = DATA.properties.filter(function (p) { return matchesType(p) && (!opts.area || p.area === opts.area); });
    model = TABS.map(function (tab) {
      var cards = [];
      props.filter(tab.has).forEach(function (p) { cards = cards.concat(buildCards(p, checkin, checkout, trolley)); });
      cards = mergeTwins(cards);
      return { tab: tab, cards: cards, open: cards.filter(function (c) { return c.section === 'open'; }).length };
    }).filter(function (m) { return m.cards.length; });
    var keys = model.map(function (m) { return m.tab.key; });
    if (state.place && !state.tab) {   // a link that names a place opens the tab that place is in
      var home = model.filter(function (m) { return m.cards.some(function (c) { return c.prop === state.place; }); })[0];
      if (home) state.tab = home.tab.key;
    }
    if (keys.indexOf(state.tab) < 0) {
      var firstOpen = model.filter(function (m) { return m.open; })[0];
      state.tab = (firstOpen || model[0] || { tab: {} }).tab.key || null;
    }
    when.textContent = nice(checkin) + ' to ' + nice(checkout) + ' · ' + plural(state.nights, 'night', 'nights');
  }

  function drawTabs() {
    tablist.textContent = '';
    bar.style.display = model.length ? '' : 'none';
    tablist.style.display = model.length > 1 ? '' : 'none';
    model.forEach(function (m, i) {
      var on = m.tab.key === state.tab;
      var b = h('button', { type: 'button', class: 'tab', role: 'tab', id: 'tab-' + m.tab.key, 'aria-selected': String(on),
        'aria-controls': 'panel', tabindex: on ? '0' : '-1' }, [
        m.tab.label,
        h('span', { class: 'pill' + (m.open ? '' : ' none'), text: m.open ? m.open + ' open' : String(m.cards.length) })
      ]);
      b.addEventListener('click', function () { pick(m.tab.key, false); });
      b.addEventListener('keydown', function (e) {
        var to = e.key === 'ArrowRight' ? i + 1 : e.key === 'ArrowLeft' ? i - 1 : e.key === 'Home' ? 0 : e.key === 'End' ? model.length - 1 : null;
        if (to === null) return;
        e.preventDefault();
        pick(model[(to + model.length) % model.length].tab.key, true);
      });
      tablist.appendChild(b);
    });
  }

  function drawPanel() {
    panel.textContent = '';
    panel.id = 'panel';
    var m = model.filter(function (x) { return x.tab.key === state.tab; })[0];
    if (!m) {
      panel.removeAttribute('aria-labelledby');
      panel.appendChild(h('p', { class: 'msg', text: 'Nothing matches that filter. Try All.' }));
      return;
    }
    panel.setAttribute('aria-labelledby', 'tab-' + m.tab.key);
    panel.appendChild(h('p', { class: 'lede', text: m.tab.intro }));
    SECTIONS.forEach(function (s) {
      var list = m.cards.filter(function (c) { return c.section === s.key; });
      if (!list.length) return;
      // Cards in a row always line up: either every card in the group gets a photo panel, or the ones with
      // photos go first in rows of their own.
      var pics = opts.photos === 'off' ? [] : list.filter(function (c) { return c.photo; });
      var plain = list.filter(function (c) { return pics.indexOf(c) < 0; });
      var unit = s.key === 'more' ? null : plural(list.length, 'place', 'places');
      panel.appendChild(h('h3', null, [s.label, unit ? h('span', { class: 'count', text: unit }) : null]));
      if (pics.length * 2 >= list.length) {
        // Most have a photo: keep the listed order and give the few without one a plain panel.
        panel.appendChild(h('div', { class: 'grid' }, list.map(function (c) { return draw(c, pics.length > 0); })));
      } else {
        if (pics.length) panel.appendChild(h('div', { class: 'grid' }, pics.map(function (c) { return draw(c, true); })));
        panel.appendChild(h('div', { class: 'grid' }, plain.map(function (c) { return draw(c, false); })));
      }
    });
  }

  function render() {
    if (!DATA) return;
    compute();
    drawTabs();
    drawPanel();
    writeAddress();
  }

  // Bring the card named in the address into view, once. A group shown listing by listing (Airbnb, Vrbo)
  // has no card of its own, so its link just opens the tab.
  function showPlace() {
    var hit = state.place && panel.querySelector('.card.hit');
    if (hit && hit.scrollIntoView) setTimeout(function () { place(); hit.scrollIntoView({ block: 'center' }); }, 60);
  }

  // Switch tabs. If the bar is pinned, bring the top of the new panel up under it.
  function pick(key, focus) {
    state.tab = key;
    drawTabs();
    drawPanel();
    writeAddress();
    var on = root.getElementById('tab-' + key);
    if (on) {
      if (focus) on.focus();
      if (on.scrollIntoView && tablist.scrollWidth > tablist.clientWidth) tablist.scrollLeft = Math.max(0, on.offsetLeft - 24);
    }
    var top = stickyTop();
    if (sentinel.getBoundingClientRect().top < top) {
      window.scrollTo(0, window.pageYOffset + sentinel.getBoundingClientRect().top - top);
    }
  }

  // Leave room for the page's own pinned header, if it has one.
  function stickyTop() {
    if (opts.stickyTop !== undefined && !isNaN(parseFloat(opts.stickyTop))) return parseFloat(opts.stickyTop);
    var hits = document.elementsFromPoint ? document.elementsFromPoint(Math.round(window.innerWidth / 2), 2) : [];
    for (var i = 0; i < hits.length; i++) {
      for (var el = hits[i]; el && el !== document.documentElement && el !== document.body; el = el.parentElement) {
        if (el === host) break;
        var pos = getComputedStyle(el).position;
        if (pos === 'fixed' || pos === 'sticky') {
          var r = el.getBoundingClientRect();
          if (r.top <= 2 && r.height < window.innerHeight / 2) return Math.round(r.bottom);
        }
      }
    }
    return 0;
  }
  var ticking = false;
  function place() {
    ticking = false;
    var top = stickyTop();
    host.style.setProperty('--top', top + 'px');
    var stuck = sentinel.getBoundingClientRect().top < top && wrap.getBoundingClientRect().bottom > top + 60;
    bar.className = stuck ? 'bar stuck' : 'bar';
  }
  function schedule() { if (!ticking) { ticking = true; (window.requestAnimationFrame || setTimeout)(place); } }

  function controls() {
    var min = today();
    var date = h('input', { type: 'date', id: 'ci', value: state.checkin, min: min, max: addDays(min, (DATA && DATA.horizon_nights) || 330) });
    date.addEventListener('change', function () { if (date.value && date.value >= min) { state.checkin = date.value; render(); } });
    var nights = h('select', { id: 'nt' });
    for (var i = 1; i <= MAX_NIGHTS; i++) nights.appendChild(h('option', { value: i, text: plural(i, 'night', 'nights') }));
    nights.value = String(state.nights);
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
    wrap.appendChild(h('p', { class: 'intro', text: 'Pick your dates to see which Medora hotels, cabins, rentals and campgrounds have room, then book directly with the property.' }));
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
    DATA.properties.forEach(function (p) { BY_ID[p.id] = p; });
    PHOTOS = (res[1] && res[1].photos) || {};
    LISTINGS = (res[1] && res[1].listings) || {};
    wrap.removeChild(loading);
    [controls(), sentinel, bar, panel, note].forEach(function (el) { wrap.appendChild(el); });
    render();
    place();
    showPlace();
    window.addEventListener('scroll', schedule, { passive: true });
    window.addEventListener('resize', schedule);
  }).catch(function () {
    loading.textContent = '';
    loading.appendChild(document.createTextNode('The lodging finder could not load. '));
    loading.appendChild(h('a', { href: 'https://www.trlibrary.com/visit/lodging', text: 'See the full list of places to stay.' }));
  });
})();
