export const $ = s => document.querySelector(s);
export const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;'
} [c]));
export const role = location.pathname === '/staff' ? 'merchant' : location.pathname === '/console' ? 'console' : 'customer';
export const yuan = c => (Number(c) / 100).toFixed(2),
  unit = u => ({
    g: '克',
    box: '盒',
    piece: '个'
  } [u] || ''),
  date = v => v ? new Date(v).toLocaleString('zh-CN', {
    timeZone: 'Asia/Shanghai',
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false
  }) : '待协商';
export const uid = () => crypto.randomUUID();
export async function api(path, method = 'GET', body) {
  let r = await fetch('/demo/api' + path, {
    method,
    credentials: 'same-origin',
    headers: {
      'X-Demo-Role': role,
      ...(body ? {
        'Content-Type': 'application/json'
      } : {})
    },
    body: body ? JSON.stringify(body) : undefined
  });
  let d = await r.json().catch(() => ({
    detail: '服务暂时无法连接'
  }));
  if (!r.ok) {
    let e = new Error(typeof d.detail === 'string' ? d.detail : '信息填写不完整，请检查后再试');
    e.status = r.status;
    throw e
  }
  return d
}
export function toast(text) {
  $('.toast')?.remove();
  let d = document.createElement('div');
  d.className = 'toast';
  d.textContent = text;
  document.body.append(d);
  setTimeout(() => d.remove(), 4200)
}
export function failure(error, target = '#error') {
  let p = $(target);
  if (p) {
    p.hidden = false;
    p.textContent = error.message || error
  } else toast(error.message || error)
}
export async function login(account) {
  await api('/login', 'POST', {
    account
  });
  location.reload()
}
export async function shell() {
  try {
    let me = await api('/me');
    $('#account').textContent = me.name;
    return me
  } catch (e) {
    $('#app').innerHTML = `<div class="login"><div class="eyebrow">QINGHE · SERVICE</div><div class="card"><h1>${role==='merchant'?'门店售后工作台':role==='console'?'演示控制台':'把新鲜，也把安心带回家'}</h1><p class="muted">${role==='customer'?'申请售后、补充材料，随时查看处理进度。':'进入预置演示身份，体验本地模拟业务。'}</p><button id="login">${role==='merchant'?'以门店客服身份进入':role==='console'?'进入演示管理员':'以顾客小林身份进入'}</button><p class="hint">演示身份 · 仅使用模拟交易，无真实资金流转</p></div><a href="/console">演示启动器 ↗</a></div>`;
    $('#login').onclick = () => login(role === 'merchant' ? 'merchant' : role === 'console' ? 'console' : 'customer');
    return null
  }
}
export function statusCard(d) {
  return `<span class="status ${esc(d.category)}">${esc(d.status)}</span>`
}
export function product(d) {
  return `<div class="productline"><div class="product-icon">${d.item?.name?.includes('榴莲')?'◒':d.item?.name?.includes('葡萄')?'✿':'◍'}</div><div><strong>${esc(d.item?.name||'待核实购买信息')}</strong><p>${esc(d.item?.spec||'没有订单也可以申请')} ${d.item?' · '+d.item.quantity+unit(d.item.unit):''}</p></div></div>`
}
export function caseCard(d) {
  return `<article class="card clickable" data-open="${esc(d.id)}" tabindex="0"><div class="row case-top"><span class="muted">${esc(d.number)}</span>${statusCard(d)}</div>${product(d)}<div class="case-description">${esc(d.description)}</div><div class="row"><small>${date(d.created)}</small><small>${esc(d.next_step||(d.task?'正在处理':'查看详情'))} →</small></div></article>`
}
export function materials(d) {
  return d.media.length ? `<div class="material-grid">${d.media.map((m,i)=>`<div class="material" data-media="${i}" role="button" tabindex="0" aria-label="查看${m.kind==='video'?'视频':materialLabel(m)}"><${m.kind==='video'?'video preload="metadata"':'img loading="lazy"'} src="${esc(m.url)}"></${m.kind==='video'?'video':'img'}><small>${m.kind==='video'?'视频 · 点击播放':materialLabel(m)+' · 点击放大'}</small></div>`).join('')}</div>` : '<p class="hint">尚未提交材料，可在沟通时补充。</p>'
}
export function bindMedia(d) {
  document.querySelectorAll('[data-media]').forEach(el => {
    el.onclick = () => {
      let m = d.media[+el.dataset.media],
        dialog = document.createElement('div');
      dialog.className = 'modal';
      dialog.innerHTML = `<button aria-label="关闭大图">×</button><${m.kind==='video'?'video controls autoplay':'img'} src="${esc(m.url)}"></${m.kind==='video'?'video':'img'}>`;
      dialog.onclick = e => {
        if (e.target === dialog || e.target.tagName === 'BUTTON') dialog.remove()
      };
      document.body.append(dialog)
    }
  })
}
export function planCard(d, staff = false) {
  let p = d.plan;
  if (!p) return `<h2>处理方案</h2><div class="empty" style="padding:25px 0"><p>${d.task?'售后服务正在处理':d.manual?'门店客服正在接待':d.closed?'本次申请已结束':'等待您补充信息'}</p><small>${d.task?'正在查看材料或查询购买信息，处理进度会及时更新。':d.manual?'请在沟通区查看门店回复。':d.closed?'处理记录已保留。':'请查看沟通区的具体问题，补充后会继续为您处理。'}</small></div>`;
  let type = {
    refund_proposal: '退款方案',
    exchange_proposal: '换货方案',
    store_inspection: '到店检查'
  } [p.type];
  return `<div class="row"><div class="eyebrow" style="margin:0">处理方案 · 第 ${p.version} 版</div><span class="status">${p.consent==='agreed'?'已确认':p.consent==='superseded'?'已更新':p.consent==='declined'?'待修改':'待您确认'}</span></div><h2 class="plan-title" style="margin-top:20px">${type}</h2><p class="muted">${esc(d.item?.name||'待核实商品')}</p>${p.type==='refund_proposal'?`<div class="amount">¥ ${yuan(p.amount_cents)}<span>拟退款金额</span></div>`:''}<ul class="specs">${p.type==='store_inspection'?'<li><span>核实事项</span><span>商品状况、异常范围及可处理数量</span></li>':`<li><span>${p.type==='refund_proposal'?'退款':'换货'}数量</span><span>${p.quantity} ${unit(d.item?.unit)}</span></li>`}${p.type==='exchange_proposal'?`<li><span>规格</span><span>${esc(d.item?.spec)}</span></li><li><span>库存与安排</span><span>${p.stock_confirmed?'门店已核对库存':'待门店核对确认'}</span></li>`:''}${p.type!=='refund_proposal'?`<li><span>${p.type==='exchange_proposal'?'预计到店':'预约时间'}</span><span>${date(p.appointment)}${!d.closed?'（待门店确认）':''}</span></li><li><span>携带材料</span><span>商品实物、购买凭证（如有）</span></li>`:''}<li><span>处理进度</span><span>${esc(p.stage)}</span></li></ul>${!staff&&p.needs_confirmation&&!d.task?'<div class="actions"><button id="agree">确认这项方案</button><button class="secondary" id="decline">希望修改</button></div>':`<p class="hint">${d.closed?(d.status==='已安排到店'?'到店安排已确认，请按时携带商品前往门店。':'本次处理已结束。'):p.consent==='agreed'?'您已确认当前版本，等待门店继续处理。':'方案更新后，请确认新的版本。'}</p>`}`
}
function materialLabel(m) { return ({product:'商品照片',receipt:'小票',weight_label:'称重标签',packaging_label:'商品标签',payment:'支付凭证',other:'其他材料',unknown:'材料 · 待识别'})[m.category] || '材料 · 待识别'; }
export function messages(d) {
  return d.messages.map(m => `<div class="bubble ${esc(m.role)}"><small>${{customer:'您',service:'售后服务',staff:'门店客服',notice:'处理进度'}[m.role]||'售后服务'} · ${date(m.created)}</small><div class="body">${esc(m.text)}</div></div>`).join('') || '<p class="hint">申请已提交，接下来会在这里沟通。</p>'
}
export class Attachments {
  constructor(target, key) {
    this.target = target;
    this.key = key;
    this.files = [];
    try {
      this.files = JSON.parse(localStorage.getItem(key) || '[]').map(f => ({
        ...f,
        preview: '/demo/api/uploads/' + f.id,
        progress: 100
      }))
    } catch {}
    this.render()
  }
  add(files, kind) {
    for (let f of files) {
      if (this.files.length >= 6) {
        toast('每次最多选择6份材料');
        break
      }
      if (!/\.(jpg|jpeg|png|webp|mp4|mov)$/i.test(f.name) || f.size > 25 * 1024 * 1024) {
        toast('请选择25MB以内的图片或视频');
        continue
      }
      this.files.push({
        file: f,
        name: f.name,
        kind: /\.(mp4|mov)$/i.test(f.name) ? 'video' : kind,
        preview: URL.createObjectURL(f),
        progress: 0,
        key: uid()
      })
    }
    this.render()
  }
  save() {
    localStorage.setItem(this.key, JSON.stringify(this.files.filter(f => f.id).map(({
      id,
      name,
      kind
    }) => ({
      id,
      name,
      kind
    }))))
  }
  render() {
    let el = $(this.target);
    if (!el) return;
    el.innerHTML = this.files.map((f, i) => `<div class="filecard"><${f.kind==='video'?'video':'img'} src="${esc(f.preview)}"></${f.kind==='video'?'video':'img'}><button type="button" data-remove="${i}" aria-label="移除${esc(f.name)}">×</button><div class="filelabel">${esc(f.kind==='receipt'?'小票 · ':'')}${esc(f.name)}${f.loading?`<progress max="100" value="${f.progress}"></progress>`:f.id?' · 已上传':''}</div>${f.error?`<button type="button" class="retry-upload" data-retry="${i}">上传失败，点击重试</button>`:''}</div>`).join('');
    el.querySelectorAll('[data-remove]').forEach(b => b.onclick = () => {
      let f = this.files[+b.dataset.remove];
      if (f.loading) return;
      this.files.splice(+b.dataset.remove, 1);
      this.save();
      this.render()
    });
    el.querySelectorAll('[data-retry]').forEach(b => b.onclick = () => this.upload(this.files[+b.dataset.retry]).catch(e => toast(e.message)))
  }
  upload(f) {
    if (f.id) return Promise.resolve(f.id);
    return new Promise((resolve, reject) => {
      if (!f.file) return reject(new Error('请重新选择这份材料'));
      let x = new XMLHttpRequest(),
        form = new FormData();
      form.append('file', f.file);
      form.append('kind', f.kind);
      f.loading = true;
      f.error = false;
      this.render();
      x.open('POST', '/demo/api/uploads');
      x.setRequestHeader('X-Demo-Role', 'customer');
      x.upload.onprogress = e => {
        if (e.lengthComputable) {
          f.progress = Math.round(100 * e.loaded / e.total);
          this.render()
        }
      };
      x.onload = () => {
        f.loading = false;
        let data;
        try {
          data = JSON.parse(x.responseText)
        } catch {}
        if (x.status >= 200 && x.status < 300) {
          f.id = data.id;
          this.save();
          this.render();
          resolve(f.id)
        } else {
          f.error = true;
          this.render();
          reject(new Error(data?.detail || '材料上传失败，请重试'))
        }
      };
      x.onerror = () => {
        f.loading = false;
        f.error = true;
        this.render();
        reject(new Error('网络暂时中断，请重试上传'))
      };
      x.send(form)
    })
  }
  async all() {
    let out = [];
    for (let f of this.files) out.push(await this.upload(f));
    return out
  }
  clear() {
    this.files = [];
    localStorage.removeItem(this.key);
    this.render()
  }
}
export function errorBox() {
  return '<p class="error" id="error" hidden role="alert"></p>'
}
