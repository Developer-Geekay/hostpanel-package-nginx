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
  const { html, useState, useCallback } = sdk;
  const { SdkFormModal, SdkConfirmModal, SdkDataTable } = sdk.components;
  const { useApi, useToast } = sdk.hooks;

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
    const [addOpen,   setAddOpen]   = useState(false);
    const [delTarget, setDelTarget] = useState(null);

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
