/* hostpanel-package-nginx — frontend/main.js
 * SDK plugin: no build step required.
 * Registered as window.__hpkg_sdk.register('nginx', NginxPlugin).
 * Uses window.__hpkg_sdk.fetch() for all API calls (auth via localStorage 'auth_token').
 *
 * NOTE: htm passes props to React.createElement, so `style` must be a JS object,
 * not a CSS string. Use style=${{ prop: 'value' }} syntax throughout.
 */
(function () {
  'use strict';

  const sdk = window.__hpkg_sdk;
  const { html, useState, useEffect, useCallback } = sdk;
  const { SdkFormModal, SdkConfirmModal, SdkDataTable } = sdk.components;
  const { useApi, useToast } = sdk.hooks;

  // ── SVGs Micro-Icons matching native dashboard style ─────────────────────────
  const SearchIcon = () => html`
    <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" style=${{ color: 'var(--text-3)', flexShrink: 0 }}>
      <circle cx="11" cy="11" r="8"></circle>
      <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
    </svg>
  `;

  // ── Vhost editor modal ──────────────────────────────────────────────────────

  function VhostEditorModal({ domain, onClose, onSaved }) {
    const { ok, err: toastErr } = useToast();
    const [content,      setContent]      = useState('');
    const [loading,      setLoading]      = useState(true);
    const [saving,       setSaving]       = useState(false);
    const [resetting,    setResetting]    = useState(false);
    const [resetConfirm, setResetConfirm] = useState(false);
    const [error,        setError]        = useState('');

    useEffect(() => {
      sdk.fetch('GET', '/cpanelapi/domains/' + domain + '/vhost')
        .then(d => { setContent(d.content); setLoading(false); })
        .catch(e => { setError(e.message || 'Failed to load vhost'); setLoading(false); });
    }, [domain]);

    useEffect(() => {
      const esc = e => { if (e.key === 'Escape') onClose(); };
      window.addEventListener('keydown', esc);
      return () => window.removeEventListener('keydown', esc);
    }, [onClose]);

    const save = async () => {
      setSaving(true); setError('');
      try {
        await sdk.fetch('PUT', '/cpanelapi/domains/' + domain + '/vhost', { content });
        ok('Vhost saved & nginx reloaded');
        if (onSaved) onSaved();
        onClose();
      } catch (e) {
        setError(e.message || 'Save failed');
      } finally {
        setSaving(false);
      }
    };

    const doReset = async () => {
      setResetConfirm(false);
      setResetting(true); setError('');
      try {
        const d = await sdk.fetch('POST', '/cpanelapi/domains/' + domain + '/vhost/reset');
        setContent(d.content);
        ok('Vhost reset to default template');
      } catch (e) {
        setError(e.message || 'Reset failed');
      } finally {
        setResetting(false);
      }
    };

    return html`
      <div class="modal-overlay" style=${{ backdropFilter: 'blur(8px)', background: 'rgba(0,0,0,0.7)' }} onClick=${e => e.target === e.currentTarget && onClose()}>
        <div class="modal animate-fade-in" style=${{ width: 740, maxWidth: '95vw' }}>
          <div class="modal-header">
            <span class="modal-title">Edit Vhost — ${domain}</span>
            <button class="modal-close" onClick=${onClose} aria-label="Close">✕</button>
          </div>
          <div class="modal-body">
            <p style=${{ fontSize: 12, color: 'var(--text-3)', marginBottom: 10, marginTop: 0 }}>
              Changes are validated with <code>nginx -t</code> before applying. nginx reloads automatically on save.
            </p>
            ${loading
              ? html`<div style=${{ color: 'var(--text-3)', fontSize: 13, padding: '32px 0', textAlign: 'center' }}>Loading…</div>`
              : html`
                  <textarea
                    value=${content}
                    onInput=${e => setContent(e.target.value)}
                    spellcheck="false"
                    autocomplete="off"
                    style=${{
                      width: '100%', boxSizing: 'border-box', height: 360,
                      resize: 'vertical', fontFamily: 'var(--font-mono)', fontSize: 12.5,
                      background: 'var(--bg-3, #151515)', color: 'var(--text, #f8f8f2)',
                      border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
                      padding: '10px 12px', outline: 'none', lineHeight: 1.65,
                      tabSize: 4,
                    }}
                  />
                `
            }
            ${error && html`
              <pre style=${{
                marginTop: 10, padding: '10px 12px', whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                background: 'var(--err-dim)', color: 'var(--err)',
                border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
                fontFamily: 'var(--font-mono)', fontSize: 11, lineHeight: 1.5,
              }}>${error}</pre>
            `}
          </div>
          <div class="modal-footer">
            <button class="btn btn-ghost btn-sm" onClick=${() => setResetConfirm(true)} disabled=${resetting || loading || saving}>
              ${resetting ? 'Resetting…' : 'Reset to Default'}
            </button>
            <div style=${{ display: 'flex', gap: 8 }}>
              <button class="btn btn-outline btn-sm" onClick=${onClose} disabled=${saving || resetting}>Cancel</button>
              <button class="btn btn-primary btn-sm" onClick=${save} disabled=${saving || loading}>
                ${saving ? 'Saving…' : 'Save & Reload Nginx'}
              </button>
            </div>
          </div>
        </div>
      </div>

      ${resetConfirm && html`
        <${SdkConfirmModal}
          open=${true}
          title="Reset to Default"
          message=${'Reset "' + domain + '" vhost to the default template? All custom changes will be lost.'}
          danger=${true}
          onClose=${() => setResetConfirm(false)}
          onConfirm=${doReset}
        />
      `}
    `;
  }

  // ── Subdomains panel (shown when a domain row is expanded) ──────────────────

  function SubdomainsPanel({ domainName, onMsg }) {
    const { data, loading, refetch } = useApi(
      () => sdk.fetch('GET', '/cpanelapi/domains/' + domainName + '/subdomains'),
      [domainName],
    );
    const [addOpen,     setAddOpen]     = useState(false);
    const [delTarget,   setDelTarget]   = useState(null);
    const [vhostTarget, setVhostTarget] = useState(null);

    const rowBase = {
      display: 'flex', alignItems: 'center', gap: 0,
      padding: '9px 16px 9px 0',
      borderTop: '1px solid var(--border-2)',
    };

    const rows = data ?? [];

    return html`
      <div>
        ${loading && html`
          <div style=${{ ...rowBase, paddingLeft: 16, color: 'var(--text-3)', fontSize: 12 }}>Loading…</div>
        `}

        ${!loading && rows.map(sub => html`
          <div key=${sub.fqdn} style=${rowBase}>
            <span style=${{ width: 40, textAlign: 'center', color: 'var(--text-3)', flexShrink: 0, fontSize: 13 }}>↳</span>
            <span class="mono" style=${{ flex: '1 1 180px', fontSize: 12.5, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: 'var(--text)' }}>
              ${sub.fqdn}
            </span>
            <span style=${{ flex: '0 0 120px', color: 'var(--text-3)', fontSize: 12 }}>—</span>
            <span style=${{ flex: '0 0 100px' }}>
              <span class=${'badge ' + (sub.status === 'active' ? 'badge-ok' : 'badge-warn')}>${sub.status}</span>
            </span>
            <span style=${{ flex: '0 0 80px' }}>
              <span class=${'badge ' + (sub.https_forced ? 'badge-ok' : 'badge-dim')}>${sub.https_forced ? 'Yes' : 'No'}</span>
            </span>
            <div style=${{ flex: '0 0 auto', display: 'flex', gap: 6 }}>
              <button class="btn btn-ghost btn-sm" onClick=${() => setVhostTarget(sub.fqdn)}>Edit Vhost</button>
              <button class="btn btn-danger btn-sm" onClick=${() => setDelTarget(sub)}>Delete</button>
            </div>
          </div>
        `)}

        <div style=${{ ...rowBase, paddingLeft: 40, gap: 12 }}>
          ${!loading && !rows.length && html`
            <span style=${{ fontSize: 12, color: 'var(--text-3)' }}>No subdomains yet</span>
          `}
          <button class="btn btn-ghost btn-sm" onClick=${() => setAddOpen(true)}>+ Add Subdomain</button>
        </div>
      </div>

      ${addOpen && html`
        <${SdkFormModal}
          open=${true}
          title=${'Add Subdomain — ' + domainName}
          fields=${[{
            key: 'subdomain', label: 'Subdomain prefix', type: 'text',
            required: true, placeholder: 'e.g. blog, api, www',
          }]}
          onClose=${() => setAddOpen(false)}
          onSubmit=${async (values) => {
            await sdk.fetch('POST', '/cpanelapi/domains/' + domainName + '/subdomains', values);
            setAddOpen(false);
            refetch();
            onMsg('Subdomain added', 'ok');
          }}
        />
      `}

      ${vhostTarget && html`
        <${VhostEditorModal}
          domain=${vhostTarget}
          onClose=${() => setVhostTarget(null)}
          onSaved=${refetch}
        />
      `}

      ${delTarget && html`
        <${SdkConfirmModal}
          open=${true}
          title="Delete Subdomain"
          message=${'Delete ' + delTarget.fqdn + '? The nginx vhost and web directory will be removed.'}
          danger=${true}
          onClose=${() => setDelTarget(null)}
          onConfirm=${async () => {
            await sdk.fetch('DELETE', '/cpanelapi/domains/' + domainName + '/subdomains/' + delTarget.subdomain);
            setDelTarget(null);
            refetch();
            onMsg('Subdomain deleted', 'ok');
          }}
        />
      `}
    `;
  }

  // ── Domains tab ─────────────────────────────────────────────────────────────

  function DomainsTab({ onMsg }) {
    const { data: domains, loading, error, refetch } = useApi(
      () => sdk.fetch('GET', '/cpanelapi/domains'),
    );
    const [search,      setSearch]      = useState('');
    const [addOpen,     setAddOpen]     = useState(false);
    const [delTarget,   setDelTarget]   = useState(null);
    const [vhostTarget, setVhostTarget] = useState(null);

    const filteredDomains = (domains ?? []).filter(d =>
      d.domain_name.toLowerCase().includes(search.toLowerCase()) ||
      d.username.toLowerCase().includes(search.toLowerCase())
    );

    return html`
      <div class="card" style=${{ padding: '20px' }}>
        <div style=${{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16, flexWrap: 'wrap', gap: 10 }}>
          <span class="card-title" style=${{ margin: 0 }}>Websites</span>
          
          <div class="search-wrap" style=${{ flex: 1, minWidth: 200, margin: 0 }}>
            <${SearchIcon} />
            <input
              type="text"
              placeholder="Filter websites..."
              value=${search}
              onInput=${e => setSearch(e.target.value)}
            />
          </div>

          <button class="btn btn-primary btn-sm" onClick=${() => setAddOpen(true)}>
            + Add Domain
          </button>
        </div>

        ${error
          ? html`<div class="empty"><div class="empty-title" style=${{ color: 'var(--err)' }}>${error}</div></div>`
          : html`
              <${SdkDataTable}
                columns=${[
                  { key: 'domain_name',  label: 'Domain' },
                  { key: 'username',     label: 'Owner' },
                  { key: 'status',       label: 'Status', type: 'badge' },
                  { key: 'https_forced', label: 'HTTPS',  type: 'bool'  },
                ]}
                rows=${filteredDomains}
                loading=${loading}
                empty=${{ title: 'No domains yet', desc: 'Add a domain to start hosting websites' }}
                renderExpanded=${(row) => html`
                  <${SubdomainsPanel} domainName=${row.domain_name} onMsg=${onMsg} />
                `}
                renderActions=${(row) => html`
                  <button class="btn btn-ghost btn-sm" onClick=${() => setVhostTarget(row.domain_name)}>
                    Edit Vhost
                  </button>
                  <button class="btn btn-danger btn-sm" onClick=${() => setDelTarget(row)}>
                    Delete
                  </button>
                `}
              />
            `
        }

        ${addOpen && html`
          <${SdkFormModal}
            open=${true}
            title="Add Domain"
            fields=${[{
              key: 'domain_name', label: 'Domain Name', type: 'text',
              required: true, placeholder: 'example.com',
            }]}
            onClose=${() => setAddOpen(false)}
            onSubmit=${async (values) => {
              await sdk.fetch('POST', '/cpanelapi/domains', values);
              setAddOpen(false);
              refetch();
              onMsg('Domain added successfully', 'ok');
            }}
          />
        `}

        ${vhostTarget && html`
          <${VhostEditorModal}
            domain=${vhostTarget}
            onClose=${() => setVhostTarget(null)}
            onSaved=${refetch}
          />
        `}

        ${delTarget && html`
          <${SdkConfirmModal}
            open=${true}
            title="Delete Domain"
            message=${'Delete ' + delTarget.domain_name + ' and all associated resources? This cannot be undone.'}
            danger=${true}
            onClose=${() => setDelTarget(null)}
            onConfirm=${async () => {
              await sdk.fetch('DELETE', '/cpanelapi/domains/' + delTarget.domain_name);
              setDelTarget(null);
              refetch();
              onMsg('Domain deleted', 'ok');
            }}
          />
        `}
      </div>
    `;
  }

  // ── Redirects tab ────────────────────────────────────────────────────────────

  function RedirectsTab({ onMsg }) {
    const { data: redirects, loading, error, refetch } = useApi(
      () => sdk.fetch('GET', '/cpanelapi/redirects'),
    );
    const [search,    setSearch]    = useState('');
    const [addOpen,   setAddOpen]   = useState(false);
    const [delTarget, setDelTarget] = useState(null);

    const filteredRedirects = (redirects ?? []).filter(r =>
      r.source_domain.toLowerCase().includes(search.toLowerCase()) ||
      r.source_path.toLowerCase().includes(search.toLowerCase()) ||
      r.destination.toLowerCase().includes(search.toLowerCase())
    );

    return html`
      <div class="card" style=${{ padding: '20px' }}>
        <div style=${{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16, flexWrap: 'wrap', gap: 10 }}>
          <span class="card-title" style=${{ margin: 0 }}>Redirects</span>
          
          <div class="search-wrap" style=${{ flex: 1, minWidth: 200, margin: 0 }}>
            <${SearchIcon} />
            <input
              type="text"
              placeholder="Filter redirects..."
              value=${search}
              onInput=${e => setSearch(e.target.value)}
            />
          </div>

          <button class="btn btn-primary btn-sm" onClick=${() => setAddOpen(true)}>
            + Add Redirect
          </button>
        </div>

        ${error
          ? html`<div class="empty"><div class="empty-title" style=${{ color: 'var(--err)' }}>${error}</div></div>`
          : html`
              <${SdkDataTable}
                columns=${[
                  { key: 'source_domain', label: 'From Domain' },
                  { key: 'source_path',   label: 'Path',        type: 'mono' },
                  { key: 'destination',   label: 'Destination', type: 'mono' },
                  { key: 'type',          label: 'Type',        type: 'badge' },
                ]}
                rows=${filteredRedirects}
                loading=${loading}
                empty=${{ title: 'No redirects', desc: 'Add 301/302 redirect rules per domain' }}
                renderActions=${(row) => html`
                  <button class="btn btn-danger btn-sm" onClick=${() => setDelTarget(row)}>
                    Delete
                  </button>
                `}
              />
            `
        }

        ${addOpen && html`
          <${SdkFormModal}
            open=${true}
            title="Add Redirect"
            fields=${[
              { key: 'source_domain', label: 'Source Domain', type: 'text', required: true, placeholder: 'example.com' },
              { key: 'source_path',  label: 'Source Path',   type: 'text', required: true, placeholder: '/old-path' },
              { key: 'destination',  label: 'Destination',   type: 'text', required: true, placeholder: 'https://example.com/new-path' },
              {
                key: 'type', label: 'Type', type: 'select', required: true,
                options: [
                  { value: 301, label: '301 Permanent' },
                  { value: 302, label: '302 Temporary' },
                ],
              },
            ]}
            onClose=${() => setAddOpen(false)}
            onSubmit=${async (values) => {
              await sdk.fetch('POST', '/cpanelapi/redirects', {
                ...values,
                type: Number(values.type),
              });
              setAddOpen(false);
              refetch();
              onMsg('Redirect added', 'ok');
            }}
          />
        `}

        ${delTarget && html`
          <${SdkConfirmModal}
            open=${true}
            title="Delete Redirect"
            message=${'Delete redirect ' + delTarget.source_domain + delTarget.source_path + ' → ' + delTarget.destination + '?'}
            danger=${true}
            onClose=${() => setDelTarget(null)}
            onConfirm=${async () => {
              await sdk.fetch('DELETE', '/cpanelapi/redirects/' + delTarget.id);
              setDelTarget(null);
              refetch();
              onMsg('Redirect deleted', 'ok');
            }}
          />
        `}
      </div>
    `;
  }

  // ── Settings tab ─────────────────────────────────────────────────────────────

  function SettingsTab({ onMsg }) {
    const [form,    setForm]    = useState(null);
    const [loading, setLoading] = useState(true);
    const [saving,  setSaving]  = useState(false);

    useEffect(() => {
      sdk.fetch('GET', '/cpanelapi/nginx/settings')
        .then(d => { setForm(d.settings); setLoading(false); })
        .catch(e => { onMsg(e.message || 'Failed to load settings', 'err'); setLoading(false); });
    }, []);

    const save = async () => {
      setSaving(true);
      try {
        await sdk.fetch('PUT', '/cpanelapi/nginx/settings', form);
        onMsg('Settings saved and nginx reloaded', 'ok');
      } catch (e) {
        onMsg(e.message || 'Save failed', 'err');
      } finally {
        setSaving(false);
      }
    };

    if (loading || !form) return html`
      <div class="card" style=${{ padding: '20px' }}>
        <div style=${{ color: 'var(--text-3)', fontSize: 13, padding: '32px 0', textAlign: 'center' }}>Loading…</div>
      </div>
    `;

    const field = (key, label, unit, hint) => html`
      <div style=${{ marginBottom: 20 }}>
        <label style=${{
          display: 'block', fontSize: 11, fontWeight: 600,
          color: 'var(--text-3)', marginBottom: 6,
          textTransform: 'uppercase', letterSpacing: '.5px',
        }}>${label}</label>
        <div style=${{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <input
            type="text"
            class="input"
            value=${form[key] ?? ''}
            onInput=${e => setForm({ ...form, [key]: e.target.value })}
            style=${{ width: 140, height: '32px', fontSize: '13px' }}
          />
          ${unit && html`<span style=${{ fontSize: 13, color: 'var(--text-2)' }}>${unit}</span>`}
        </div>
        ${hint && html`<p style=${{ fontSize: 11.5, color: 'var(--text-3)', margin: '6px 0 0' }}>${hint}</p>`}
      </div>
    `;

    return html`
      <div class="card" style=${{ padding: '20px' }}>
        <div style=${{ marginBottom: 24 }}>
          <span class="card-title">Nginx Settings</span>
          <p style=${{ fontSize: 13, color: 'var(--text-3)', margin: '4px 0 0' }}>
            Changes apply immediately — nginx.conf is rewritten and all panel vhosts are regenerated.
          </p>
        </div>

        ${field('client_max_body_size', 'Max Upload Size', '', 'e.g. 50m, 100m, 1g — controls the 413 Request Entity Too Large limit')}
        ${field('keepalive_timeout',    'Keepalive Timeout',    'seconds', 'How long to keep idle connections open')}
        ${field('worker_connections',   'Worker Connections',   'connections', 'Max simultaneous connections per nginx worker process')}
        ${field('proxy_read_timeout',   'Proxy Read Timeout',   'seconds', 'Timeout for reading a response from the panel backend')}

        <div style=${{ display: 'flex', justifyContent: 'flex-end', marginTop: 8 }}>
          <button class="btn btn-primary btn-md" onClick=${save} disabled=${saving}>
            ${saving ? 'Saving…' : 'Save & Reload Nginx'}
          </button>
        </div>
      </div>
    `;
  }

  // ── Root component ───────────────────────────────────────────────────────────

  function NginxPlugin() {
    const [tab, setTab]           = useState('domains');
    const { ok, err: toastErr }   = useToast();

    const onMsg = useCallback((msg, kind) => {
      if (kind === 'ok') ok(msg); else toastErr(msg);
    }, [ok, toastErr]);

    return html`
      <div class="page">
        <div class="page-header">
          <div>
            <h1 class="page-title">Web Server</h1>
            <p class="page-desc">Nginx virtual hosts, redirects & settings</p>
          </div>
        </div>

        <div class="tab-bar" style=${{ marginBottom: 20 }}>
          <button
            class=${'tab' + (tab === 'domains'   ? ' active' : '')}
            onClick=${() => setTab('domains')}
          >Websites</button>
          <button
            class=${'tab' + (tab === 'redirects' ? ' active' : '')}
            onClick=${() => setTab('redirects')}
          >Redirects</button>
          <button
            class=${'tab' + (tab === 'settings'  ? ' active' : '')}
            onClick=${() => setTab('settings')}
          >Settings</button>
        </div>

        ${tab === 'domains'
          ? html`<${DomainsTab}   onMsg=${onMsg} />`
          : tab === 'redirects'
          ? html`<${RedirectsTab} onMsg=${onMsg} />`
          : html`<${SettingsTab}  onMsg=${onMsg} />`
        }
      </div>
    `;
  }

  window.__hpkg_sdk.register('nginx', NginxPlugin);
})();
