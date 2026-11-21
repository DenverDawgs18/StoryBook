// StoryBook analytics, privacy-first.
//
// First-party: every page view and the named events below go to this site's own server (/api/track),
// which keeps aggregate counts for the owner's dashboard at /admin. No cookies, no names or emails;
// only the path, the referring site, UTM tags and which story is playing. See server/analytics.py.
//
// PostHog (optional), off unless the server is configured:
// - The project key comes from the server (`/api/config`, set with the POSTHOG_KEY env var),
//   so a static copy of the site, or a server without the key, sends nothing at all.
// - No cookies or local storage ("memory" persistence), no session recordings, no autocapture.
//   Autocapture would record the text of clicked elements, which on the personalised page can
//   include a child's name. Only the named events below are sent, and none of them carry names
//   or email addresses.
// - Visitors with Do Not Track switched on are not tracked.
//
// Pages call window.sbTrack("event_name", {props}). Calls made before PostHog has loaded are queued.
// Any element with data-track="event_name" (plus optional data-track-* attributes) reports a click.
(function () {
  const queue = [];
  let ready = false;
  const dnt = navigator.doNotTrack === "1" || window.doNotTrack === "1";
  const local = location.protocol === "file:";
  function beacon(data) {
    if (dnt || local) return;
    const body = JSON.stringify(data);
    try {
      if (navigator.sendBeacon && navigator.sendBeacon("/api/track", new Blob([body], { type: "text/plain" }))) return;
    } catch (e) { /* fall through */ }
    fetch("/api/track", { method: "POST", body, keepalive: true, headers: { "Content-Type": "text/plain" } }).catch(() => {});
  }
  window.sbTrack = function (event, props) {
    beacon({ ev: event, path: location.pathname, props: props || {} });
    if (ready) window.posthog.capture(event, props || {});
    else queue.push([event, props || {}]);
  };

  // One first-party page view per page load, with where the visitor came from.
  const q = new URLSearchParams(location.search);
  const pv = { ev: "pageview", path: location.pathname, ref: document.referrer || "", story: q.get("ep") || "" };
  for (const k of ["utm_source", "utm_medium", "utm_campaign", "utm_content"]) if (q.get(k)) pv[k] = q.get(k);
  beacon(pv);

  document.addEventListener("click", (e) => {
    const el = e.target.closest?.("[data-track]");
    if (!el) return;
    const props = {};
    for (const [k, v] of Object.entries(el.dataset)) {
      if (k.startsWith("track") && k !== "track") props[k.slice(5).replace(/^./, (c) => c.toLowerCase())] = v;
    }
    window.sbTrack(el.dataset.track, props);
  });

  if (dnt) return;

  fetch("/api/config", { cache: "no-cache" })
    .then((r) => (r.ok ? r.json() : null))
    .then((cfg) => {
      if (!cfg || !cfg.posthog_key) return;
      // PostHog's official loader snippet: it queues calls until the library arrives.
      !function(t,e){var o,n,p,r;e.__SV||(window.posthog=e,e._i=[],e.init=function(i,s,a){function g(t,e){var o=e.split(".");2==o.length&&(t=t[o[0]],e=o[1]),t[e]=function(){t.push([e].concat(Array.prototype.slice.call(arguments,0)))}}(p=t.createElement("script")).type="text/javascript",p.crossOrigin="anonymous",p.async=!0,p.src=s.api_host.replace(".i.posthog.com","-assets.i.posthog.com")+"/static/array.js",(r=t.getElementsByTagName("script")[0]).parentNode.insertBefore(p,r);var u=e;for(void 0!==a?u=e[a]=[]:a="posthog",u.people=u.people||[],u.toString=function(t){var e="posthog";return"posthog"!==a&&(e+="."+a),t||(e+=" (stub)"),e},u.people.toString=function(){return u.toString(1)+".people (stub)"},o="init capture register register_once register_for_session unregister unregister_for_session getFeatureFlag getFeatureFlagPayload isFeatureEnabled reloadFeatureFlags on onFeatureFlags onSessionId identify setPersonProperties group resetGroups reset get_distinct_id getGroups get_session_id alias set_config opt_in_capturing opt_out_capturing has_opted_in_capturing has_opted_out_capturing clear_opt_in_out_capturing debug".split(" "),n=0;n<o.length;n++)g(u,o[n]);e._i.push([i,s,a])},e.__SV=1)}(document,window.posthog||[]);
      window.posthog.init(cfg.posthog_key, {
        api_host: cfg.posthog_host || "https://us.i.posthog.com",
        persistence: "memory",          // no cookies, no localStorage: no consent banner needed
        person_profiles: "identified_only",
        autocapture: false,             // see above: clicked text could include a child's name
        capture_pageview: true,
        capture_pageleave: true,
        disable_session_recording: true,
        enable_heatmaps: false,
        capture_dead_clicks: false,
        respect_dnt: true,
      });
      ready = true;
      for (const [ev, props] of queue.splice(0)) window.posthog.capture(ev, props);
    })
    .catch(() => { /* no server or no analytics: stay silent */ });
})();
