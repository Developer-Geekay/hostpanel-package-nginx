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

  // ── Vhost editor modal ──────────────────────────────────────────────────────

  function VhostEditorModal({ domain, onClose, onSaved }) {
    const { ok, err: toastErr } = useToast();
    const [content,   setContent]   = useState('');
    const [loading,   setLoading]   = useState(true);
    const [saving,    setSaving]    = useState(false);
    const [resetting, setResetting] = useState(false);
    const [error,     setError]     = useState('');

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

    const reset = async () => {
      if (!confirm('Reset "' + domain + '" vhost to the default template? Custom changes will be lost.')) return;
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
      <div class="modal-overlay" onClick=${e => e.target === e.currentTarget && onClose()}>
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
                      resize: 'vertical', fontFamily: 'var(--font-mono)', fontSize: 12,
                      background: 'var(--bg)', color: 'var(--text)',
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
                background: 'rgba(239,68,68,.08)', color: 'var(--err, #ef4444)',
                border: '1px solid rgba(239,68,68,.2)', borderRadius: 'var(--radius-sm)',
                fontFamily: 'var(--font-mono)', fontSize: 11, lineHeight: 1.5,
              }}>${error}</pre>
            `}
          </div>
          <div class="modal-footer">
            <button class="btn btn-ghost btn-sm" onClick=${reset} disabled=${resetting || loading || saving}>
              ${resetting ? 'Resetting…' : 'Reset to Default'}
            </button>
            <div style=${{ display: 'flex', gap: 8 }}>
              <button class="btn btn-outline btn-md" onClick=${onClose} disabled=${saving || resetting}>Cancel</button>
              <button class="btn btn-primary btn-md" onClick=${save} disabled=${saving || loading}>
                ${saving ? 'Saving…' : 'Save & Reload Nginx'}
              </button>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  // ── Subdomains panel (shown when a domain row is expanded) ──────────────────

  function SubdomainsPanel({ domainName, onMsg }) {
    const { data, loading, refetch } = useApi(
      () => sdk.fetch('GET', '/cpanelapi/domains/' + domainName + '/subdomains'),
      [domainName],
    );
    const [addOpen,   setAddOpen]   = useState(false);
    const [delTarget, setDelTarget] = useState(null);

    return html`
      <div style=${{ padding: '12px 16px 16px', background: 'var(--bg-3)', borderTop: '1px solid var(--border-2)' }}>
        <div style=${{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
          <span style=${{ fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '.08em', color: 'var(--text-2)' }}>
            Subdomains
          </span>
          <button class="btn btn-ghost btn-sm" onClick=${() => setAddOpen(true)}>+ Add</button>
        </div>

        ${loading
          ? html`<div style=${{ color: 'var(--text-3)', fontSize: 12 }}>Loading…</div>`
          : !data?.length
            ? html`<div style=${{ color: 'var(--text-3)', fontSize: 12 }}>No subdomains yet</div>`
            : html`
                <${SdkDataTable}
                  columns=${[
                    { key: 'fqdn',   label: 'FQDN',   type: 'mono' },
                    { key: 'status', label: 'Status', type: 'badge' },
                  ]}
                  rows=${data}
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
            title=${'Add Subdomain — ' + domainName}
            fields=${[{
              key: 'subdomain', label: 'Subdomain Label', type: 'text',
              required: true, placeholder: 'www',
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

        ${delTarget && html`
          <${SdkConfirmModal}
            open=${true}
            title="Delete Subdomain"
            message=${'Delete ' + delTarget.fqdn + '? The directory will be removed.'}
            danger=${true}
            onClose=${() => setDelTarget(null)}
            onConfirm=${async () => {
              await sdk.fetch(
                'DELETE',
                '/cpanelapi/domains/' + domainName + '/subdomains/' + delTarget.subdomain,
              );
              setDelTarget(null);
              refetch();
              onMsg('Subdomain deleted', 'ok');
            }}
          />
        `}
      </div>
    `;
  }

  // ── Domains tab ─────────────────────────────────────────────────────────────

  function DomainsTab({ onMsg }) {
    const { data: domains, loading, error, refetch } = useApi(
      () => sdk.fetch('GET', '/cpanelapi/domains'),
    );
    const [addOpen,     setAddOpen]     = useState(false);
    const [delTarget,   setDelTarget]   = useState(null);
    const [vhostTarget, setVhostTarget] = useState(null);

    return html`
      <div class="card">
        <div style=${{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
          <span class="card-title">Websites</span>
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
                rows=${domains ?? []}
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
    const [addOpen,   setAddOpen]   = useState(false);
    const [delTarget, setDelTarget] = useState(null);

    return html`
      <div class="card">
        <div style=${{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
          <span class="card-title">Redirects</span>
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
                rows=${redirects ?? []}
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
              {
                key: 'source_domain', label: 'Source Domain', type: 'select-from-api',
                source: '/cpanelapi/domains', option_value: 'domain_name',
                option_label: 'domain_name', required: true,
              },
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
            <p class="page-desc">Nginx virtual hosts & redirects</p>
          </div>
        </div>

        <div style=${{ display: 'flex', gap: 8, marginBottom: 20 }}>
          <button
            class=${'btn btn-sm ' + (tab === 'domains'   ? 'btn-primary' : 'btn-ghost')}
            onClick=${() => setTab('domains')}
          >Websites</button>
          <button
            class=${'btn btn-sm ' + (tab === 'redirects' ? 'btn-primary' : 'btn-ghost')}
            onClick=${() => setTab('redirects')}
          >Redirects</button>
        </div>

        ${tab === 'domains'
          ? html`<${DomainsTab}   onMsg=${onMsg} />`
          : html`<${RedirectsTab} onMsg=${onMsg} />`
        }
      </div>
    `;
  }

  window.__hpkg_sdk.register('nginx', NginxPlugin);
})();
