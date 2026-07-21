/* hostpanel-package-nginx — frontend/main.js
 * SDK plugin: no build step required.
 * Registered as window.__hpkg_sdk.register('nginx', NginxPlugin).
 * Redesigned to match the design mockup: split-view layout.
 */
(function () {
  'use strict';

  const sdk = window.__hpkg_sdk;
  const { html, useState, useEffect, useCallback, useMemo } = sdk;
  const { SdkConfirmModal } = sdk.components;
  const { useApi, useToast } = sdk.hooks;

  // ── Inline SVG icons ─────────────────────────────────────────────────────────

  const GlobeIcon = ({ color = 'var(--text-3)', size = 14 }) => html`
    <svg xmlns="http://www.w3.org/2000/svg" width=${size} height=${size} viewBox="0 0 24 24" fill="none" stroke=${color} stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/>
      <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>
    </svg>`;

  const CodeIcon = ({ color = 'var(--text-3)', size = 14 }) => html`
    <svg xmlns="http://www.w3.org/2000/svg" width=${size} height=${size} viewBox="0 0 24 24" fill="none" stroke=${color} stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>
    </svg>`;

  const ServerIcon = ({ color = 'var(--text-3)', size = 14 }) => html`
    <svg xmlns="http://www.w3.org/2000/svg" width=${size} height=${size} viewBox="0 0 24 24" fill="none" stroke=${color} stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <rect x="2" y="2" width="20" height="8" rx="2" ry="2"/><rect x="2" y="14" width="20" height="8" rx="2" ry="2"/>
      <line x1="6" y1="6" x2="6.01" y2="6"/><line x1="6" y1="18" x2="6.01" y2="18"/>
    </svg>`;

  const SaveIcon = ({ size = 12 }) => html`
    <svg xmlns="http://www.w3.org/2000/svg" width=${size} height=${size} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/>
      <polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/>
    </svg>`;

  const TrashIcon = ({ size = 11 }) => html`
    <svg xmlns="http://www.w3.org/2000/svg" width=${size} height=${size} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/>
    </svg>`;

  // ── VHost Config inline editor ───────────────────────────────────────────────

  function VhostConfigEditor({ domain, onSaved }) {
    const { ok, err: toastErr } = useToast();
    const [content, setContent] = useState('');
    const [path, setPath] = useState('');
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [resetting, setResetting] = useState(false);
    const [confirmReset, setConfirmReset] = useState(false);
    const [error, setError] = useState('');

    useEffect(() => {
      if (!domain) return;
      setLoading(true);
      sdk.fetch('GET', '/cpanelapi/domains/' + domain + '/vhost')
        .then(d => { setContent(d.content || ''); setPath(d.path || ''); setLoading(false); })
        .catch(e => { setError(e.message || 'Failed to load vhost'); setLoading(false); });
    }, [domain]);

    const save = async () => {
      setSaving(true); setError('');
      try {
        await sdk.fetch('PUT', '/cpanelapi/domains/' + domain + '/vhost', { content });
        ok('Vhost saved & nginx reloaded');
        if (onSaved) onSaved();
      } catch (e) {
        setError(e.message || 'Save failed');
      } finally {
        setSaving(false);
      }
    };

    const doReset = async () => {
      setConfirmReset(false);
      setResetting(true);
      try {
        const d = await sdk.fetch('POST', '/cpanelapi/domains/' + domain + '/vhost/reset');
        setContent(d.content || '');
        ok('Vhost reset to default');
      } catch (e) {
        toastErr(e.message || 'Reset failed');
      } finally {
        setResetting(false);
      }
    };

    if (loading) return html`<div style=${{ padding: '24px', textAlign: 'center', color: 'var(--text-3)', fontSize: 13 }}>Loading config…</div>`;

    return html`
      <div class="animate-fade-in" style=${{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div style=${{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <div class="mono" title=${path} style=${{ height: 32, display: 'flex', alignItems: 'center', fontSize: 12, flex: 1, maxWidth: 360, background: 'var(--bg-3)', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', color: 'var(--text-2)', padding: '0 10px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            ${path || '—'}
          </div>
          <button class="btn btn-primary btn-sm" onClick=${save} disabled=${saving || loading}>
            <${SaveIcon} /> ${saving ? 'Saving…' : 'Save & Reload'}
          </button>
          <button class="btn btn-ghost btn-sm" onClick=${() => setConfirmReset(true)} disabled=${resetting || saving}>
            ${resetting ? 'Resetting…' : 'Reset'}
          </button>
        </div>

        <textarea
          value=${content}
          onInput=${e => setContent(e.target.value)}
          spellcheck="false"
          autocomplete="off"
          style=${{
            width: '100%', boxSizing: 'border-box', height: 300,
            resize: 'vertical', fontFamily: 'var(--font-mono)', fontSize: 12,
            background: 'var(--bg)', color: 'var(--text)',
            border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
            padding: '10px 12px', outline: 'none', lineHeight: 1.65,
            tabSize: 4,
          }}
        />

        ${error && html`
          <div style=${{ color: 'var(--err)', fontSize: 12, padding: '8px 12px', background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)', borderRadius: 'var(--radius-sm)' }}>
            ${error}
          </div>`}

        ${confirmReset && html`
          <${SdkConfirmModal}
            open=${true}
            title="Reset to Default"
            message=${'Reset "' + domain + '" vhost to the default template? All custom changes will be lost.'}
            danger=${true}
            onClose=${() => setConfirmReset(false)}
            onConfirm=${doReset}
          />`}
      </div>`;
  }

  // ── Add VHost inline form ────────────────────────────────────────────────────

  function AddVhostForm({ onCancel, onCreated }) {
    const { ok, err: toastErr } = useToast();
    const [formDomain, setFormDomain] = useState('');
    const [formAliases, setFormAliases] = useState('');
    const [formRoot, setFormRoot] = useState('/var/www/');
    const [formPhp, setFormPhp] = useState('php8.3-fpm');
    const [formProxy, setFormProxy] = useState('');
    const [formBackendType, setFormBackendType] = useState('static');
    const [formHttps, setFormHttps] = useState(true);
    const [formForceHttps, setFormForceHttps] = useState(true);
    const [formGzip, setFormGzip] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');

    const submit = async (e) => {
      e.preventDefault();
      setError('');
      if (!formDomain.trim()) { setError('Domain name is required'); return; }
      setBusy(true);
      try {
        await sdk.fetch('POST', '/cpanelapi/domains', {
          domain_name: formDomain.trim(),
          aliases: formAliases.trim(),
          document_root: formRoot.trim(),
          php_version: formBackendType === 'static' ? formPhp : '',
          proxy_pass: formBackendType === 'proxy' ? formProxy.trim() : '',
          https_enabled: formHttps,
          https_forced: formForceHttps,
          gzip_enabled: formGzip,
        });
        ok('Virtual host created');
        onCreated();
      } catch (e) {
        setError(e.message || 'Failed to create vhost');
      } finally {
        setBusy(false);
      }
    };

    const checkStyle = (checked) => ({
      display: 'flex', alignItems: 'center', gap: 10, padding: '10px 12px',
      background: 'var(--bg-3)', border: '1px solid var(--border)',
      borderRadius: 8, cursor: 'pointer',
    });

    return html`
      <div class="animate-fade-in" style=${{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0, overflow: 'hidden', padding: 0 }}>
        <div class="split-pane-header" style=${{ padding: '14px 20px', borderBottom: '1px solid var(--border)', flexShrink: 0, display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style=${{ width: 30, height: 30, borderRadius: 8, background: 'var(--accent-dim)', border: '1px solid var(--accent-border)', display: 'grid', placeItems: 'center', flexShrink: 0 }}>
            <${GlobeIcon} color="var(--accent)" size=${15} />
          </div>
          <h3 style=${{ margin: 0, flex: 1 }}>New Virtual Host</h3>
          <button class="btn btn-ghost btn-sm" onClick=${onCancel}>✕</button>
        </div>
        <div style=${{ flex: 1, overflowY: 'auto', padding: '20px 24px' }}>
          <form onSubmit=${submit}>

            <div style=${{ fontSize: 10, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--text-3)', marginBottom: 14, display: 'flex', alignItems: 'center', gap: 10 }}>
              Domain<div style=${{ flex: 1, height: 1, background: 'var(--border)' }}></div>
            </div>

            <div style=${{ display: 'flex', gap: 12, marginBottom: 13 }}>
              <div style=${{ flex: 1 }}>
                <label class="form-label">Domain Name <span style=${{ color: 'var(--err)' }}>*</span></label>
                <input class="form-input" placeholder="e.g. newsite.example.com" value=${formDomain} onInput=${e => setFormDomain(e.target.value)} required />
              </div>
              <div style=${{ width: 200 }}>
                <label class="form-label">Aliases (optional)</label>
                <input class="form-input" placeholder="www.newsite.example.com" value=${formAliases} onInput=${e => setFormAliases(e.target.value)} />
              </div>
            </div>

            <div style=${{ display: 'flex', gap: 12, marginBottom: 13 }}>
              <div style=${{ flex: 1 }}>
                <label class="form-label">Document Root <span style=${{ color: 'var(--err)' }}>*</span></label>
                <input class="form-input" value=${formRoot} onInput=${e => setFormRoot(e.target.value)} required />
              </div>
            </div>

            <div style=${{ fontSize: 10, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--text-3)', margin: '18px 0 14px', display: 'flex', alignItems: 'center', gap: 10 }}>
              Backend<div style=${{ flex: 1, height: 1, background: 'var(--border)' }}></div>
            </div>

            <div style=${{ display: 'flex', gap: 8, marginBottom: 14 }}>
              <label style=${{ flex: 1, display: 'flex', alignItems: 'flex-start', gap: 10, padding: 12, background: 'var(--bg-3)', border: formBackendType === 'static' ? '2px solid var(--accent)' : '1px solid var(--border)', borderRadius: 8, cursor: 'pointer' }}>
                <input type="radio" name="wstype" value="static" checked=${formBackendType === 'static'} onChange=${() => setFormBackendType('static')} style=${{ accentColor: 'var(--accent)', marginTop: 2 }} />
                <div>
                  <div style=${{ fontSize: 12.5, fontWeight: 500, color: 'var(--text)' }}>Static / PHP</div>
                  <div style=${{ fontSize: 11, color: 'var(--text-3)' }}>Serve files from document root</div>
                </div>
              </label>
              <label style=${{ flex: 1, display: 'flex', alignItems: 'flex-start', gap: 10, padding: 12, background: 'var(--bg-3)', border: formBackendType === 'proxy' ? '2px solid var(--accent)' : '1px solid var(--border)', borderRadius: 8, cursor: 'pointer' }}>
                <input type="radio" name="wstype" value="proxy" checked=${formBackendType === 'proxy'} onChange=${() => setFormBackendType('proxy')} style=${{ accentColor: 'var(--accent)', marginTop: 2 }} />
                <div>
                  <div style=${{ fontSize: 12.5, fontWeight: 500, color: 'var(--text)' }}>Reverse Proxy</div>
                  <div style=${{ fontSize: 11, color: 'var(--text-3)' }}>Forward to Node.js / app server</div>
                </div>
              </label>
            </div>

            <div style=${{ display: 'flex', gap: 12, marginBottom: 13 }}>
              ${formBackendType === 'static' && html`
                <div style=${{ flex: 1 }}>
                  <label class="form-label">PHP Version</label>
                  <select class="form-select" style=${{ width: '100%' }} value=${formPhp} onChange=${e => setFormPhp(e.target.value)}>
                    <option value="">None (static)</option>
                    <option value="php8.3-fpm">PHP 8.3 (FPM)</option>
                    <option value="php8.2-fpm">PHP 8.2 (FPM)</option>
                    <option value="php8.1-fpm">PHP 8.1 (FPM)</option>
                  </select>
                </div>`}
              ${formBackendType === 'proxy' && html`
                <div style=${{ flex: 1 }}>
                  <label class="form-label">Proxy Pass</label>
                  <input class="form-input" placeholder="http://127.0.0.1:3000" value=${formProxy} onInput=${e => setFormProxy(e.target.value)} />
                </div>`}
            </div>

            <div style=${{ fontSize: 10, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--text-3)', margin: '18px 0 14px', display: 'flex', alignItems: 'center', gap: 10 }}>
              SSL & Access<div style=${{ flex: 1, height: 1, background: 'var(--border)' }}></div>
            </div>

            <div style=${{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 14 }}>
              <label style=${checkStyle(formHttps)}>
                <input type="checkbox" checked=${formHttps} onChange=${e => setFormHttps(e.target.checked)} style=${{ accentColor: 'var(--accent)', width: 14, height: 14 }} />
                <div>
                  <div style=${{ fontSize: 12.5, fontWeight: 500, color: 'var(--text)' }}>Enable HTTPS</div>
                  <div style=${{ fontSize: 11, color: 'var(--text-3)' }}>Issue Let's Encrypt cert</div>
                </div>
              </label>
              <label style=${checkStyle(formForceHttps)}>
                <input type="checkbox" checked=${formForceHttps} onChange=${e => setFormForceHttps(e.target.checked)} style=${{ accentColor: 'var(--accent)', width: 14, height: 14 }} />
                <div>
                  <div style=${{ fontSize: 12.5, fontWeight: 500, color: 'var(--text)' }}>Force HTTPS</div>
                  <div style=${{ fontSize: 11, color: 'var(--text-3)' }}>Redirect HTTP → HTTPS</div>
                </div>
              </label>
              <label style=${checkStyle(formGzip)}>
                <input type="checkbox" checked=${formGzip} onChange=${e => setFormGzip(e.target.checked)} style=${{ accentColor: 'var(--accent)', width: 14, height: 14 }} />
                <div>
                  <div style=${{ fontSize: 12.5, fontWeight: 500, color: 'var(--text)' }}>Enable Gzip</div>
                  <div style=${{ fontSize: 11, color: 'var(--text-3)' }}>Compress responses</div>
                </div>
              </label>
            </div>

            ${error && html`<div style=${{ color: 'var(--err)', fontSize: 12, marginBottom: 12 }}>${error}</div>`}

            <div style=${{ display: 'flex', gap: 8, paddingTop: 14, borderTop: '1px solid var(--border)' }}>
              <button type="submit" class="btn btn-primary btn-sm" disabled=${busy}>
                ${busy ? 'Creating…' : 'Create VHost'}
              </button>
              <button type="button" class="btn btn-outline btn-sm" onClick=${onCancel} disabled=${busy}>Cancel</button>
            </div>
          </form>
        </div>
      </div>`;
  }

  // ── VHost-only inline form (writes just the nginx block; no user/DNS/folders) ─

  function AddVhostOnlyForm({ onCancel, onCreated }) {
    const { ok } = useToast();
    const [formDomain, setFormDomain] = useState('');
    const [formAliases, setFormAliases] = useState('');
    const [formRoot, setFormRoot] = useState('/var/www/');
    const [formPhp, setFormPhp] = useState('');
    const [formProxy, setFormProxy] = useState('');
    const [formBackendType, setFormBackendType] = useState('static');
    const [formGzip, setFormGzip] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');

    const submit = async (e) => {
      e.preventDefault();
      setError('');
      if (!formDomain.trim()) { setError('Domain name is required'); return; }
      if (formBackendType === 'static' && !formRoot.trim()) { setError('Document root is required'); return; }
      setBusy(true);
      try {
        await sdk.fetch('POST', '/cpanelapi/domains/vhost-only', {
          domain_name: formDomain.trim(),
          aliases: formAliases.trim(),
          document_root: formRoot.trim(),
          php_version: formBackendType === 'static' ? formPhp : '',
          proxy_pass: formBackendType === 'proxy' ? formProxy.trim() : '',
          gzip_enabled: formGzip,
        });
        ok('Config-only vhost created');
        onCreated();
      } catch (e) {
        setError(e.message || 'Failed to create vhost');
      } finally {
        setBusy(false);
      }
    };

    const checkStyle = (checked) => ({
      display: 'flex', alignItems: 'center', gap: 10, padding: '10px 12px',
      background: 'var(--bg-3)', border: '1px solid var(--border)',
      borderRadius: 8, cursor: 'pointer',
    });

    return html`
      <div class="animate-fade-in" style=${{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0, overflow: 'hidden', padding: 0 }}>
        <div class="split-pane-header" style=${{ padding: '14px 20px', borderBottom: '1px solid var(--border)', flexShrink: 0, display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style=${{ width: 30, height: 30, borderRadius: 8, background: 'var(--accent-dim)', border: '1px solid var(--accent-border)', display: 'grid', placeItems: 'center', flexShrink: 0 }}>
            <${CodeIcon} color="var(--accent)" size=${15} />
          </div>
          <h3 style=${{ margin: 0, flex: 1 }}>New VHost (config only)</h3>
          <button class="btn btn-ghost btn-sm" onClick=${onCancel}>✕</button>
        </div>
        <div style=${{ flex: 1, overflowY: 'auto', padding: '20px 24px' }}>
          <form onSubmit=${submit}>

            <div style=${{ fontSize: 11.5, color: 'var(--text-3)', lineHeight: 1.55, marginBottom: 18, padding: '10px 12px', background: 'var(--bg-3)', border: '1px solid var(--border)', borderRadius: 8 }}>
              Writes only the nginx server block — no Linux user, <span class="mono">public_html</span>, or DNS
              zone. You own DNS, the document root, and TLS. It's listed here as a <strong>config-only</strong>
              host (hidden from the SSL tab); remove it anytime with Delete on its row.
            </div>

            <div style=${{ fontSize: 10, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--text-3)', marginBottom: 14, display: 'flex', alignItems: 'center', gap: 10 }}>
              Domain<div style=${{ flex: 1, height: 1, background: 'var(--border)' }}></div>
            </div>

            <div style=${{ display: 'flex', gap: 12, marginBottom: 13 }}>
              <div style=${{ flex: 1 }}>
                <label class="form-label">Domain Name <span style=${{ color: 'var(--err)' }}>*</span></label>
                <input class="form-input" placeholder="e.g. app.example.com" value=${formDomain} onInput=${e => setFormDomain(e.target.value)} required />
              </div>
              <div style=${{ width: 200 }}>
                <label class="form-label">Aliases (optional)</label>
                <input class="form-input" placeholder="www.app.example.com" value=${formAliases} onInput=${e => setFormAliases(e.target.value)} />
              </div>
            </div>

            <div style=${{ fontSize: 10, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--text-3)', margin: '18px 0 14px', display: 'flex', alignItems: 'center', gap: 10 }}>
              Backend<div style=${{ flex: 1, height: 1, background: 'var(--border)' }}></div>
            </div>

            <div style=${{ display: 'flex', gap: 8, marginBottom: 14 }}>
              <label style=${{ flex: 1, display: 'flex', alignItems: 'flex-start', gap: 10, padding: 12, background: 'var(--bg-3)', border: formBackendType === 'static' ? '2px solid var(--accent)' : '1px solid var(--border)', borderRadius: 8, cursor: 'pointer' }}>
                <input type="radio" name="vhotype" value="static" checked=${formBackendType === 'static'} onChange=${() => setFormBackendType('static')} style=${{ accentColor: 'var(--accent)', marginTop: 2 }} />
                <div>
                  <div style=${{ fontSize: 12.5, fontWeight: 500, color: 'var(--text)' }}>Static / PHP</div>
                  <div style=${{ fontSize: 11, color: 'var(--text-3)' }}>Serve files from document root</div>
                </div>
              </label>
              <label style=${{ flex: 1, display: 'flex', alignItems: 'flex-start', gap: 10, padding: 12, background: 'var(--bg-3)', border: formBackendType === 'proxy' ? '2px solid var(--accent)' : '1px solid var(--border)', borderRadius: 8, cursor: 'pointer' }}>
                <input type="radio" name="vhotype" value="proxy" checked=${formBackendType === 'proxy'} onChange=${() => setFormBackendType('proxy')} style=${{ accentColor: 'var(--accent)', marginTop: 2 }} />
                <div>
                  <div style=${{ fontSize: 12.5, fontWeight: 500, color: 'var(--text)' }}>Reverse Proxy</div>
                  <div style=${{ fontSize: 11, color: 'var(--text-3)' }}>Forward to an app server</div>
                </div>
              </label>
            </div>

            ${formBackendType === 'static' && html`
              <div style=${{ marginBottom: 13 }}>
                <label class="form-label">Document Root <span style=${{ color: 'var(--err)' }}>*</span></label>
                <input class="form-input" value=${formRoot} onInput=${e => setFormRoot(e.target.value)} required />
                <div style=${{ fontSize: 11, color: 'var(--text-3)', marginTop: 5 }}>Used verbatim as the nginx root — create this directory yourself.</div>
              </div>
              <div style=${{ marginBottom: 13 }}>
                <label class="form-label">PHP Version</label>
                <select class="form-select" style=${{ width: '100%' }} value=${formPhp} onChange=${e => setFormPhp(e.target.value)}>
                  <option value="">None (static)</option>
                  <option value="php8.3-fpm">PHP 8.3 (FPM)</option>
                  <option value="php8.2-fpm">PHP 8.2 (FPM)</option>
                  <option value="php8.1-fpm">PHP 8.1 (FPM)</option>
                </select>
              </div>`}

            ${formBackendType === 'proxy' && html`
              <div style=${{ marginBottom: 13 }}>
                <label class="form-label">Proxy Pass</label>
                <input class="form-input" placeholder="http://127.0.0.1:3000" value=${formProxy} onInput=${e => setFormProxy(e.target.value)} />
              </div>`}

            <div style=${{ fontSize: 10, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--text-3)', margin: '18px 0 14px', display: 'flex', alignItems: 'center', gap: 10 }}>
              Options<div style=${{ flex: 1, height: 1, background: 'var(--border)' }}></div>
            </div>

            <div style=${{ marginBottom: 14 }}>
              <label style=${checkStyle(formGzip)}>
                <input type="checkbox" checked=${formGzip} onChange=${e => setFormGzip(e.target.checked)} style=${{ accentColor: 'var(--accent)', width: 14, height: 14 }} />
                <div>
                  <div style=${{ fontSize: 12.5, fontWeight: 500, color: 'var(--text)' }}>Enable Gzip</div>
                  <div style=${{ fontSize: 11, color: 'var(--text-3)' }}>Compress responses</div>
                </div>
              </label>
            </div>

            ${error && html`<div style=${{ color: 'var(--err)', fontSize: 12, marginBottom: 12 }}>${error}</div>`}

            <div style=${{ display: 'flex', gap: 8, paddingTop: 14, borderTop: '1px solid var(--border)' }}>
              <button type="submit" class="btn btn-primary btn-sm" disabled=${busy}>
                ${busy ? 'Creating…' : 'Create VHost'}
              </button>
              <button type="button" class="btn btn-outline btn-sm" onClick=${onCancel} disabled=${busy}>Cancel</button>
            </div>
          </form>
        </div>
      </div>`;
  }

  // ── Domain Redirects tab component ──────────────────────────────────────────

  function RedirectsPane({ domainName }) {
    const { ok, err: toastErr } = useToast();
    const { data: redirects, loading, error, refetch } = useApi(
      () => sdk.fetch('GET', '/cpanelapi/redirects'),
    );
    const [path, setPath] = useState('');
    const [dest, setDest] = useState('');
    const [type, setType] = useState('301');
    const [adding, setAdding] = useState(false);
    const [deleting, setDeleting] = useState(null);

    const filtered = (redirects || []).filter(r => r.source_domain === domainName);

    const handleAdd = async (e) => {
      e.preventDefault();
      if (!path.trim() || !dest.trim()) return;
      setAdding(true);
      try {
        let srcPath = path.trim();
        if (!srcPath.startsWith('/')) srcPath = '/' + srcPath;
        await sdk.fetch('POST', '/cpanelapi/redirects', {
          source_domain: domainName,
          source_path: srcPath,
          destination: dest.trim(),
          type: Number(type),
          www_handling: 'both'
        });
        ok('Redirect added successfully');
        setPath('');
        setDest('');
        refetch();
      } catch (err) {
        toastErr(err.message || 'Failed to add redirect');
      } finally {
        setAdding(false);
      }
    };

    const handleDelete = async (id) => {
      setDeleting(id);
      try {
        await sdk.fetch('DELETE', '/cpanelapi/redirects/' + id);
        ok('Redirect deleted successfully');
        refetch();
      } catch (err) {
        toastErr(err.message || 'Failed to delete redirect');
      } finally {
        setDeleting(null);
      }
    };

    return html`
      <div class="animate-fade-in" style=${{ flex: 1, overflowY: 'auto', padding: '16px 18px' }}>
        
        <!-- Add Redirect form -->
        <div class="card" style=${{ padding: 16, marginBottom: 16 }}>
          <div style=${{ fontSize: 12, fontWeight: 600, color: 'var(--text-2)', marginBottom: 12 }}>Add New Redirect</div>
          <form onSubmit=${handleAdd} style=${{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div style=${{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
              <div style=${{ flex: 1, minWidth: 150 }}>
                <label class="form-label" style=${{ marginBottom: 4 }}>Source Path</label>
                <input class="form-input" style=${{ width: '100%' }} placeholder="e.g. /old-path" value=${path} onInput=${e => setPath(e.target.value)} required />
              </div>
              <div style=${{ flex: 2, minWidth: 200 }}>
                <label class="form-label" style=${{ marginBottom: 4 }}>Destination URL</label>
                <input class="form-input" style=${{ width: '100%' }} placeholder="e.g. https://example.com/new-path" value=${dest} onInput=${e => setDest(e.target.value)} required />
              </div>
              <div style=${{ width: 140 }}>
                <label class="form-label" style=${{ marginBottom: 4 }}>Type</label>
                <select class="form-select" style=${{ width: '100%' }} value=${type} onChange=${e => setType(e.target.value)}>
                  <option value="301">301 Permanent</option>
                  <option value="302">302 Temporary</option>
                </select>
              </div>
            </div>
            <div style=${{ display: 'flex', justifyContent: 'flex-end', marginTop: 4 }}>
              <button type="submit" class="btn btn-primary btn-sm" disabled=${adding || !path.trim() || !dest.trim()}>
                ${adding ? 'Adding…' : 'Add Redirect'}
              </button>
            </div>
          </form>
        </div>

        <!-- Redirects list table -->
        <div class="card" style=${{ padding: 0, overflow: 'hidden' }}>
          <div style=${{ padding: '14px 16px', borderBottom: '1px solid var(--border-2)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style=${{ fontSize: 12, fontWeight: 600, color: 'var(--text-2)' }}>Active Redirects</span>
            <span class="chip chip-accent">${filtered.length}</span>
          </div>
          ${loading
            ? html`<div style=${{ color: 'var(--text-3)', fontSize: 12.5, padding: 20, textAlign: 'center' }}>Loading redirects…</div>`
            : filtered.length === 0
            ? html`<div style=${{ color: 'var(--text-3)', fontSize: 12.5, padding: 24, textAlign: 'center' }}>No redirects defined for this domain.</div>`
            : html`
                <div class="table-wrap">
                  <table style=${{ tableLayout: 'fixed', width: '100%' }}>
                    <thead>
                      <tr>
                        <th style=${{ width: '30%' }}>Path</th>
                        <th style=${{ width: '45%' }}>Destination</th>
                        <th style=${{ width: '15%' }}>Type</th>
                        <th style=${{ width: '10%', textAlign: 'right' }}>Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      ${filtered.map(r => html`
                        <tr key=${r.id}>
                          <td class="mono" style=${{ fontSize: 12, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>${r.source_path}</td>
                          <td class="mono" style=${{ fontSize: 12, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>${r.destination}</td>
                          <td>
                            <span class=${'chip ' + (r.type === 301 ? 'chip-green' : 'chip-amber')} style=${{ fontSize: 10 }}>
                              ${r.type === 301 ? '301 Perm' : '302 Temp'}
                            </span>
                          </td>
                          <td style=${{ textAlign: 'right' }}>
                            <button class="btn btn-ghost btn-sm" style=${{ padding: 4, color: 'var(--err)' }} onClick=${() => handleDelete(r.id)} disabled=${deleting === r.id}>
                              🗑
                            </button>
                          </td>
                        </tr>
                      `)}
                    </tbody>
                  </table>
                </div>
              `}
        </div>
      </div>
    `;
  }

  // ── VHost Detail view ────────────────────────────────────────────────────────

  function VhostDetail({ domain, onDeleted, onRefetch }) {
    const { ok, err: toastErr } = useToast();
    const [activeTab, setActiveTab] = useState('config');
    const [confirmDel, setConfirmDel] = useState(false);
    const [logs, setLogs] = useState('');
    const [logsLoading, setLogsLoading] = useState(false);

    const isHttps = domain.https_forced || domain.https_enabled;
    const isProxy = !!(domain.proxy_pass);

    const iconColor = isHttps ? 'var(--green)' : isProxy ? 'var(--blue)' : 'var(--accent)';
    const iconBg = isHttps ? 'var(--green-dim)' : isProxy ? 'var(--blue-dim)' : 'var(--accent-dim)';

    const handleTab = (t) => {
      setActiveTab(t);
      if (t === 'logs' && !logs) {
        setLogsLoading(true);
        sdk.fetch('GET', '/cpanelapi/domains/' + domain.domain_name + '/logs')
          .then(d => setLogs((d.lines || []).join('\n') || 'No access logs found'))
          .catch(e => setLogs('Error: ' + (e.message || 'Failed to load logs')))
          .finally(() => setLogsLoading(false));
      }
    };

    const deleteDomain = async () => {
      try {
        await sdk.fetch('DELETE', '/cpanelapi/domains/' + domain.domain_name);
        ok('Domain deleted');
        onDeleted();
      } catch (e) {
        toastErr(e.message || 'Delete failed');
      } finally {
        setConfirmDel(false);
      }
    };

    return html`
      <div class="animate-fade-in" style=${{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0, overflow: 'hidden' }}>
        
        <!-- Detail Header -->
        <div class="split-pane-header" style=${{ padding: '14px 20px', borderBottom: '1px solid var(--border)', flexShrink: 0 }}>
          <div style=${{ width: 36, height: 36, borderRadius: 9, background: iconBg, border: '1px solid ' + (isHttps ? 'var(--green-border)' : 'var(--border)'), display: 'grid', placeItems: 'center', flexShrink: 0 }}>
            ${isProxy
              ? html`<${CodeIcon} color=${iconColor} size=${16} />`
              : html`<${GlobeIcon} color=${iconColor} size=${16} />`}
          </div>
          <div style=${{ flex: 1, minWidth: 0 }}>
            <h3 style=${{ margin: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>${domain.domain_name}</h3>
            <div class="mono" style=${{ fontSize: 10, color: 'var(--text-3)', marginTop: 2 }}>
              ${domain.document_root}${domain.php_version ? ' · ' + domain.php_version : ''}${domain.proxy_pass ? ' → ' + domain.proxy_pass : ''}
            </div>
          </div>
          <span class=${'chip ' + (domain.status === 'active' ? 'chip-green' : 'chip-gray')}>
            ${domain.status || 'active'}
          </span>
          <button class="btn btn-danger btn-sm" onClick=${() => setConfirmDel(true)}>
            <${TrashIcon} /> Delete
          </button>
        </div>

        <!-- Tab Bar -->
        <div class="tab-bar" style=${{ padding: '0 18px', borderBottom: '1px solid var(--border)', flexShrink: 0 }}>
          <button class=${'tab' + (activeTab === 'config' ? ' active' : '')} onClick=${() => handleTab('config')}>
            ⚙ Config
          </button>
          <button class=${'tab' + (activeTab === 'logs' ? ' active' : '')} onClick=${() => handleTab('logs')}>
            📄 Access Logs
          </button>
          <button class=${'tab' + (activeTab === 'ssl' ? ' active' : '')} onClick=${() => handleTab('ssl')}>
            🔒 SSL
          </button>
          <button class=${'tab' + (activeTab === 'redirects' ? ' active' : '')} onClick=${() => handleTab('redirects')}>
            🔗 Redirects
          </button>
        </div>

        <!-- Tab: Config -->
        ${activeTab === 'config' && html`
          <div class="animate-fade-in" style=${{ flex: 1, overflowY: 'auto' }}>
            <!-- Quick stat cards row -->
            <div style=${{ padding: '14px 18px', borderBottom: '1px solid var(--border)', display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10 }}>
              <div class="card" style=${{ padding: '10px 12px' }}>
                <div class="form-label" style=${{ marginBottom: 3 }}>Document Root</div>
                <div class="mono" style=${{ fontSize: 11.5, color: 'var(--text)' }}>${domain.document_root || '—'}</div>
              </div>
              <div class="card" style=${{ padding: '10px 12px' }}>
                <div class="form-label" style=${{ marginBottom: 3 }}>PHP / Backend</div>
                <div style=${{ fontSize: 12.5, color: 'var(--text)' }}>${domain.php_version || (domain.proxy_pass ? 'Reverse Proxy' : 'None')}</div>
              </div>
              <div class="card" style=${{ padding: '10px 12px' }}>
                <div class="form-label" style=${{ marginBottom: 3 }}>HTTPS</div>
                <div style=${{ fontSize: 12.5, color: domain.vhost_only ? 'var(--text-3)' : (isHttps ? 'var(--ok)' : 'var(--text-3)') }}>
                  ${domain.vhost_only ? 'Managed in config' : (domain.https_forced ? 'Enabled · forced' : domain.https_enabled ? 'Enabled' : 'Disabled')}
                </div>
              </div>
            </div>
            <!-- Code editor -->
            <div style=${{ padding: '14px 18px' }}>
              <${VhostConfigEditor} domain=${domain.domain_name} onSaved=${onRefetch} />
            </div>
          </div>`}

        <!-- Tab: Access Logs -->
        ${activeTab === 'logs' && html`
          <div class="animate-fade-in" style=${{ flex: 1, overflowY: 'auto', padding: '16px 18px' }}>
            ${logsLoading
              ? html`<div style=${{ textAlign: 'center', padding: 24, color: 'var(--text-3)' }}>Loading logs…</div>`
              : html`
                  <pre style=${{
                    fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-2)',
                    background: 'var(--bg)', border: '1px solid var(--border)',
                    borderRadius: 'var(--radius-sm)', padding: 12, whiteSpace: 'pre-wrap',
                    wordBreak: 'break-all', maxHeight: 500, overflowY: 'auto', margin: 0,
                  }}>${logs || 'No logs loaded yet'}</pre>`}
          </div>`}

        <!-- Tab: SSL -->
        ${activeTab === 'ssl' && html`
          <div class="animate-fade-in" style=${{ flex: 1, overflowY: 'auto', padding: '16px 18px' }}>
            <div class="card" style=${{ padding: 16, marginBottom: 14 }}>
              <div style=${{ fontSize: 12, fontWeight: 600, color: 'var(--text-2)', marginBottom: 12 }}>SSL Certificate Status</div>
              <div style=${{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px 24px' }}>
                ${[
                  ['HTTPS Enabled', domain.vhost_only ? 'Managed in config' : (domain.https_enabled ? 'Yes' : 'No')],
                  ['HTTPS Forced', domain.vhost_only ? 'Managed in config' : (domain.https_forced ? 'Yes' : 'No')],
                  ['Domain', domain.domain_name],
                  ['Status', domain.vhost_only ? 'config-only' : (domain.status || 'active')],
                ].map(([k, v]) => html`
                  <div key=${k} style=${{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid var(--border)' }}>
                     <span style=${{ fontSize: 12, color: 'var(--text-3)' }}>${k}</span>
                     <span style=${{ fontSize: 12, color: 'var(--text)' }}>${v}</span>
                  </div>`)}
              </div>
            </div>
            <p style=${{ fontSize: 12.5, color: 'var(--text-3)' }}>
              To issue or renew Let's Encrypt certificates, use the SSL section in the main panel.
            </p>
          </div>`}

        <!-- Tab: Redirects -->
        ${activeTab === 'redirects' && html`
          <${RedirectsPane} domainName=${domain.domain_name} />
        `}

        ${confirmDel && html`
          <${SdkConfirmModal}
            open=${true}
            title="Delete Domain"
            message=${'Delete ' + domain.domain_name + ' and all associated nginx config? This cannot be undone.'}
            danger=${true}
            onClose=${() => setConfirmDel(false)}
            onConfirm=${deleteDomain}
          />`}
      </div>`;
  }

  // ── Settings tab ─────────────────────────────────────────────────────────────

  function SettingsTab() {
    const { ok, err: toastErr } = useToast();
    const [form,    setForm]    = useState(null);
    const [loading, setLoading] = useState(true);
    const [saving,  setSaving]  = useState(false);

    useEffect(() => {
      sdk.fetch('GET', '/cpanelapi/nginx/settings')
        .then(d => { setForm(d.settings); setLoading(false); })
        .catch(e => { toastErr(e.message || 'Failed to load settings'); setLoading(false); });
    }, []);

    const save = async (e) => {
      e.preventDefault();
      setSaving(true);
      try {
        await sdk.fetch('PUT', '/cpanelapi/nginx/settings', form);
        ok('Settings saved and nginx reloaded');
      } catch (e) {
        toastErr(e.message || 'Save failed');
      } finally {
        setSaving(false);
      }
    };

    if (loading) return html`
      <div style=${{ padding: '32px 0', textAlign: 'center', color: 'var(--text-3)', fontSize: 13 }}>Loading settings…</div>
    `;

    const field = (key, label, unit, hint) => html`
      <div class="field" style=${{ marginBottom: 20 }}>
        <label style=${{
          display: 'block', fontSize: 11, fontWeight: 500,
          color: 'var(--text-2)', marginBottom: 6,
          textTransform: 'uppercase', letterSpacing: '.5px',
        }}>${label}</label>
        <div style=${{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <input
            type="text"
            value=${form[key] ?? ''}
            onInput=${e => setForm({ ...form, [key]: e.target.value })}
            style=${{ width: 140 }}
            required
          />
          ${unit && html`<span style=${{ fontSize: 13, color: 'var(--text-3)' }}>${unit}</span>`}
        </div>
        ${hint && html`<p style=${{ fontSize: 11, color: 'var(--text-3)', margin: '4px 0 0' }}>${hint}</p>`}
      </div>
    `;

    return html`
      <div class="animate-fade-in" style=${{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0, overflow: 'hidden' }}>
        <div class="split-pane-header" style=${{ padding: '14px 20px', borderBottom: '1px solid var(--border)', flexShrink: 0 }}>
          <h3 style=${{ margin: 0 }}>Nginx Global Settings</h3>
        </div>
        
        <div style=${{ flex: 1, overflowY: 'auto', padding: '20px 24px' }}>
          <p style=${{ fontSize: 13, color: 'var(--text-3)', margin: '0 0 24px' }}>
            Changes apply immediately — nginx.conf is rewritten and all panel vhosts are regenerated.
          </p>

          <form onSubmit=${save}>
            ${field('client_max_body_size', 'Max Upload Size', '', 'e.g. 50m, 100m, 1g — controls the 413 Request Entity Too Large limit')}
            ${field('keepalive_timeout',    'Keepalive Timeout',    'seconds', 'How long to keep idle connections open')}
            ${field('worker_connections',   'Worker Connections',   'connections', 'Max simultaneous connections per nginx worker process')}
            ${field('proxy_read_timeout',   'Proxy Read Timeout',   'seconds', 'Timeout for reading a response from the panel backend')}

            <div style=${{ display: 'flex', justifyContent: 'flex-end', marginTop: 12 }}>
              <button type="submit" class="btn btn-primary btn-sm" disabled=${saving}>
                ${saving ? 'Saving…' : 'Save & Reload Nginx'}
              </button>
            </div>
          </form>
        </div>
      </div>
    `;
  }

  // ── Root NginxPlugin ─────────────────────────────────────────────────────────

  function NginxPlugin() {
    const { ok, err: toastErr } = useToast();
    const { data: domains, loading, error, refetch } = useApi(
      () => sdk.fetch('GET', '/cpanelapi/domains'),
    );
    const [search, setSearch] = useState('');
    const [selectedDomain, setSelectedDomain] = useState(null);
    const [addingNew, setAddingNew] = useState(false);
    const [addingVhostOnly, setAddingVhostOnly] = useState(false);
    const [editingSettings, setEditingSettings] = useState(false);

    const filtered = useMemo(() => {
      const list = domains ?? [];
      if (!search.trim()) return list;
      const q = search.toLowerCase();
      return list.filter(d =>
        d.domain_name.toLowerCase().includes(q) ||
        (d.username || '').toLowerCase().includes(q)
      );
    }, [domains, search]);

    // After domain list loads, auto-select first one
    useEffect(() => {
      if (!selectedDomain && domains && domains.length > 0 && !addingNew && !addingVhostOnly && !editingSettings) {
        setSelectedDomain(domains[0]);
      }
    }, [domains, editingSettings]);

    const selectDomain = (d) => {
      setSelectedDomain(d);
      setAddingNew(false);
      setAddingVhostOnly(false);
      setEditingSettings(false);
    };

    const triggerAdd = () => {
      setAddingNew(true);
      setAddingVhostOnly(false);
      setSelectedDomain(null);
      setEditingSettings(false);
    };

    const triggerAddVhostOnly = () => {
      setAddingVhostOnly(true);
      setAddingNew(false);
      setSelectedDomain(null);
      setEditingSettings(false);
    };

    const triggerSettings = () => {
      setEditingSettings(true);
      setAddingNew(false);
      setAddingVhostOnly(false);
      setSelectedDomain(null);
    };

    const onCreated = () => {
      setAddingNew(false);
      setAddingVhostOnly(false);
      refetch();
    };

    const onDeleted = () => {
      setSelectedDomain(null);
      refetch();
    };

    const onRefetch = () => refetch();

    const getIcon = (d) => {
      if (d.proxy_pass) return html`<${CodeIcon} color="var(--blue)" size=${14} />`;
      if (d.https_enabled || d.https_forced) return html`<${GlobeIcon} color="var(--green)" size=${14} />`;
      return html`<${ServerIcon} color="var(--text-3)" size=${14} />`;
    };

    const getIconBg = (d) => {
      if (d.proxy_pass) return 'var(--blue-dim)';
      if (d.https_enabled || d.https_forced) return 'var(--green-dim)';
      return 'var(--bg-3)';
    };

    return html`
      <div class="page" style=${{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0, overflow: 'hidden', padding: '24px' }}>
        
        <!-- Page Header -->
        <div class="page-header" style=${{ flexShrink: 0, marginBottom: 16, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div>
            <h1 class="page-title">Web Server</h1>
            <p class="page-desc">
              Nginx virtual hosts${domains ? ' · ' + domains.length + ' vhosts' : ''}
            </p>
          </div>
          <div style=${{ display: 'flex', gap: 8 }}>
            <button class="btn btn-outline btn-sm" onClick=${triggerSettings} style=${{ display: 'flex', alignItems: 'center', gap: 5 }}>
              ⚙ Settings
            </button>
            <button class="btn btn-outline btn-sm" onClick=${triggerAddVhostOnly}>+ VHost Only</button>
            <button class="btn btn-primary btn-sm" onClick=${triggerAdd}>+ Add VHost</button>
          </div>
        </div>

        <!-- Split View -->
        <div class="split-view" style=${{ flex: 1, minHeight: 0 }}>
          
          <!-- Left Panel: VHost List -->
          <div class="split-left" style=${{ display: 'flex', flexDirection: 'column' }}>
            <div class="split-pane-header" style=${{ padding: '10px 14px', borderBottom: '1px solid var(--border)', flexShrink: 0 }}>
              <h3>Virtual Hosts</h3>
              <span class="chip chip-accent">${(domains ?? []).length}</span>
            </div>
            <div class="search-wrap" style=${{ margin: '8px 10px', padding: '0 10px' }}>
              <input
                type="text"
                placeholder="Filter vhosts…"
                value=${search}
                onInput=${e => setSearch(e.target.value)}
                style=${{ width: '100%' }}
              />
            </div>
            <div class="split-scroll" style=${{ flex: 1, overflowY: 'auto' }}>
              <div style=${{ height: 6 }}></div>
              ${loading && html`<div style=${{ color: 'var(--text-3)', padding: 20, textAlign: 'center', fontSize: 12.5 }}>Loading…</div>`}
              ${error && html`<div style=${{ color: 'var(--err)', padding: 20, fontSize: 12.5 }}>${error}</div>`}
              ${!loading && filtered.length === 0 && html`
                <div class="empty" style=${{ padding: '24px 16px' }}>
                  <div class="empty-title">No domains</div>
                  <div class="empty-desc" style=${{ fontSize: 11 }}>Click "+ Add VHost" to create one.</div>
                </div>`}
              ${filtered.map(d => html`
                <div
                  key=${d.domain_name}
                  class=${'list-item ' + (selectedDomain?.domain_name === d.domain_name && !editingSettings ? 'sel' : '')}
                  onClick=${() => selectDomain(d)}
                >
                  <div class="li-icon" style=${{ background: getIconBg(d) }}>
                    ${getIcon(d)}
                  </div>
                  <div style=${{ flex: 1, minWidth: 0 }}>
                    <div class="li-name">${d.domain_name}</div>
                    <div class="li-sub">
                      ${d.vhost_only ? 'Config-only' : (d.https_forced ? 'HTTPS' : 'HTTP')}${d.php_version ? ' · ' + d.php_version : ''}${d.proxy_pass ? ' · Proxy' : ''}
                    </div>
                  </div>
                  ${d.vhost_only
                    ? html`<span class="chip chip-accent" style=${{ fontSize: 10 }} title="nginx config only — no user/DNS, hidden from SSL">config</span>`
                    : html`<span class=${'chip ' + (d.status === 'active' ? 'chip-green' : 'chip-gray')} style=${{ fontSize: 10 }}>${d.status || 'active'}</span>`}
                </div>`)}
            </div>
          </div>

          <!-- Right Panel -->
          <div class="split-right" style=${{ display: 'flex', flexDirection: 'column', minHeight: 0, overflow: 'hidden' }}>
            ${editingSettings
              ? html`<${SettingsTab} />`
              : addingNew
              ? html`<${AddVhostForm} onCancel=${() => setAddingNew(false)} onCreated=${onCreated} />`
              : addingVhostOnly
              ? html`<${AddVhostOnlyForm} onCancel=${() => setAddingVhostOnly(false)} onCreated=${onCreated} />`
              : selectedDomain
              ? html`<${VhostDetail} domain=${selectedDomain} onDeleted=${onDeleted} onRefetch=${onRefetch} />`
              : html`
                  <div class="empty" style=${{ flex: 1 }}>
                    <div class="empty-icon">🌐</div>
                    <div class="empty-title">No VHost Selected</div>
                    <div class="empty-desc">Select a virtual host from the left panel, or click "+ Add VHost" to create a new one.</div>
                  </div>`}
          </div>
        </div>
      </div>`;
  }

  window.__hpkg_sdk.register('nginx', NginxPlugin);
})();
