import {
  $,
  esc,
  api,
  shell,
  toast,
  failure,
  uid,
  date,
  yuan,
  unit,
  product,
  statusCard,
  caseCard,
  materials,
  bindMedia,
  planCard,
  messages,
  Attachments,
  errorBox
} from './shared.js';
let selected = null,
  files = null,
  locked = false,
  lastMessage = '',
  pendingKey = null,
  me = await shell();

function key(payload) {
  let fingerprint = JSON.stringify(payload);
  if (pendingKey?.fingerprint !== fingerprint) pendingKey = {
    fingerprint,
    id: uid()
  };
  return pendingKey.id
}

function navigate(id) {
  location.hash = id || ''
}
if (me) {
  await route();
  window.addEventListener('hashchange', route);
  setInterval(poll, 1500)
}
async function route() {
  selected = null;
  pendingKey = null;
  let id = location.hash.slice(1);
  try {
    if (id === 'new') await form();
    else if (id) await detail(id);
    else await home()
  } catch (e) {
    failure(e)
  }
}
async function home() {
  let r = await api('/applications');
  $('#app').innerHTML = `<div class="customer-shell"><div class="eyebrow">QINGHE FRESH · CARE</div><section class="hero"><div class="eyebrow">青禾鲜选 · 邻里店</div><h1>每一份新鲜，<br>都有安心回应。</h1><p>商品有疑问？告诉我们，门店会和您一起妥善处理。</p><button id="apply">申请售后 <span aria-hidden="true">↗</span></button><svg class="hero-art" viewBox="0 0 200 200" aria-hidden="true"><ellipse cx="110" cy="120" rx="70" ry="76" fill="#aac08d"/><path d="M110 55Q80 0 29 29Q55 79 110 55" fill="#63875a"/><path d="M110 65Q149 4 177 19Q173 65 110 65" fill="#8caa74"/><path d="M110 55L112 0" stroke="#64815b" stroke-width="6"/></svg></section><div class="section-title"><h2>我的售后 <small>${r.applications.length?'· '+r.applications.length:''}</small></h2><button class="ghost" id="refresh">刷新</button></div><div id="list">${r.applications.map(caseCard).join('')||'<div class="card empty"><div style="font-size:32px">◌</div><h2>暂时没有售后申请</h2><p>每一份申请的处理进度，都会保存在这里。</p><button class="secondary" id="first">发起第一份申请</button></div>'}</div><p class="hint" style="text-align:center">青禾鲜选 · 邻里店　08:00 – 21:00<br>演示环境 · 所有处理均为本地模拟</p></div>`;
  $('#apply').onclick = () => navigate('new');
  $('#first')?.addEventListener('click', () => navigate('new'));
  $('#refresh').onclick = home;
  bindCards()
}

function bindCards() {
  document.querySelectorAll('[data-open]').forEach(el => {
    el.onclick = () => navigate(el.dataset.open);
    el.onkeydown = e => {
      if (e.key === 'Enter') navigate(el.dataset.open)
    }
  })
}
async function form() {
  let {
    orders
  } = await api('/orders'), draft = JSON.parse(localStorage.getItem('fresh-application-draft') || '{}');
  $('#app').innerHTML = `<div class="customer-shell"><button class="ghost back" id="back">← 我的售后</button><div class="eyebrow">NEW REQUEST</div><h1>申请售后</h1><p class="muted">选择有疑问的商品，告诉我们遇到的问题。</p><form class="card" id="application">${errorBox()}<h2>购买信息</h2><label for="item">本次申请的商品</label><select id="item" required><option value="">请选择订单商品</option>${orders.flatMap(o=>o.items.map(i=>`<option value="${esc(i.item_id)}">${esc(i.name)} · ${i.quantity}${unit(i.unit)} · ¥${yuan(i.paid_cents)}</option>`)).join('')}<option value="no-order">找不到订单 / 没有小票</option></select><p class="hint" id="order-note">一份申请对应一项商品。多件商品有问题，可分别申请。</p><div class="divider"></div><h2>遇到了什么问题？</h2><label for="description">问题描述</label><textarea id="description" maxlength="4000" placeholder="例如：今天打开后发现部分果肉颜色不对，希望门店帮忙检查。" required></textarea><label for="intent">希望如何处理</label><select id="intent"><option value="unknown">与门店协商</option><option value="refund">退款</option><option value="exchange">换货</option><option value="store_inspection">到店检查</option></select><label>补充材料 <small>选填</small></label><div class="uploadbox"><div><strong style="font-size:13px">商品照片、视频或小票</strong><p class="hint" style="margin-bottom:0">最多6份，每份不超过25MB。</p></div><div><small>自动识别材料类型</small><button type="button" class="secondary" id="choose">选择材料</button></div></div><input type="file" class="file-input" id="inputfiles" multiple accept="image/jpeg,image/png,image/webp,video/mp4,video/quicktime"><div class="files" id="draftfiles"></div><p class="hint">照片和视频仅作为核实材料；您可以在提交前移除或重新选择。</p><div class="actions"><button type="submit" id="submit">提交售后申请</button></div></form></div>`;
  $('#item').value = draft.item || '';
  function showOrderNote() {
    let order = orders.find(o => o.items.some(i => i.item_id === $('#item').value));
    let item = order?.items.find(i => i.item_id === $('#item').value);
    $('#order-note').textContent = item ? `${item.spec} · ${date(order.purchased_at)}购买 · 实付 ¥${yuan(item.paid_cents)}` : '一份申请对应一项商品。没有订单也可以申请。';
  }
  $('#item').onchange = showOrderNote;
  showOrderNote();
  $('#description').value = draft.text || '';
  $('#intent').value = draft.intent || 'unknown';
  files = new Attachments('#draftfiles', 'fresh-application-files');
  $('#back').onclick = () => navigate('');
  $('#choose').onclick = () => $('#inputfiles').click();
  $('#inputfiles').onchange = e => {
    files.add(e.target.files, 'auto');
    e.target.value = ''
  };
  $('#application').oninput = () => localStorage.setItem('fresh-application-draft', JSON.stringify({
    item: $('#item').value,
    text: $('#description').value,
    intent: $('#intent').value
  }));
  $('#application').onsubmit = async e => {
    e.preventDefault();
    if (locked) return;
    if (!$('#item').value) return failure(new Error('请选择本次申请的商品，或选择找不到订单'));
    if (!$('#description').value.trim()) return failure(new Error('请填写问题描述'));
    locked = true;
    $('#submit').disabled = true;
    $('#submit').textContent = '正在提交…';
    try {
      let uploads = await files.all(),
        payload = {
          description: $('#description').value.trim(),
          desired: $('#intent').value,
          item_id: $('#item').value === 'no-order' ? null : $('#item').value,
          uploads
        };
      let r = await api('/applications', 'POST', {
        ...payload,
        request_key: key(payload)
      });
      files.clear();
      localStorage.removeItem('fresh-application-draft');
      toast(r.created ? '申请已提交，可在这里继续沟通' : '该商品已有进行中的申请，已为您打开');
      navigate(r.application)
    } catch (e) {
      failure(e)
    } finally {
      locked = false;
      if ($('#submit')) {
        $('#submit').disabled = false;
        $('#submit').textContent = '提交售后申请'
      }
    }
  }
}
async function detail(id) {
  let d = await api('/applications/' + id);
  selected = id;
  lastMessage = '';
  $('#app').innerHTML = `<div class="customer-shell"><button class="ghost back" id="back">← 我的售后</button><div class="row wrap"><div><div class="eyebrow">${esc(d.number)}</div><h1>售后详情</h1></div><div id="status"></div></div><div class="steps" id="steps"></div><div id="progress"></div>${errorBox()}<div class="detail-grid"><div><section class="card"><div class="section-title"><h2>与门店沟通</h2><small>青禾鲜选 · 邻里店</small></div><div class="messages" id="messages"></div><button class="new-message" id="newmessages" hidden>有新消息，点击查看 ↓</button><form class="composer" id="composer"><textarea id="message" aria-label="回复门店" maxlength="4000" placeholder="回复门店，或补充您想说的…"></textarea><div class="files" id="replyfiles"></div><div class="row"><div class="gap"><small>自动识别</small><button type="button" class="ghost" id="attach">＋ 材料</button></div><button id="send">发送</button></div><input type="file" id="replyinput" class="file-input" multiple accept="image/jpeg,image/png,image/webp,video/mp4,video/quicktime"></form><div id="closed" class="hint" hidden>本次申请已结束。若其他商品需要帮助，可以发起新申请。</div></section><section class="card"><h2>已提交材料</h2><div id="materials"></div></section></div><aside><section class="card" id="plan"></section><section class="card"><h2>申请信息</h2>${product(d)}<div class="divider"></div><p style="font-size:14px;overflow-wrap:anywhere">${esc(d.description)}</p><small>提交于 ${date(d.created)}<br>处理意向：<span id="current-intent">${esc(d.intent)}</span></small></section></aside></div></div>`;
  $('#back').onclick = () => navigate('');
  files = new Attachments('#replyfiles', 'fresh-reply-files-' + id);
  $('#message').value = localStorage.getItem('fresh-reply-' + id) || '';
  $('#message').oninput = () => localStorage.setItem('fresh-reply-' + id, $('#message').value);
  $('#attach').onclick = () => $('#replyinput').click();
  $('#replyinput').onchange = e => {
    files.add(e.target.files, 'auto');
    e.target.value = ''
  };
  $('#composer').onsubmit = send;
  $('#newmessages').onclick = () => {
    $('#messages').scrollTop = $('#messages').scrollHeight;
    $('#newmessages').hidden = true
  };
  paint(d)
}

function paint(d) {
  if (selected !== d.id) return;
  $('#status').innerHTML = statusCard(d);
  let steps = ['申请已提交', '核实与沟通', '确认方案', '门店处理'];
  $('#steps').innerHTML = steps.map((x, i) => `<div class="step ${(i<2||(d.plan&&i===2)||(d.closed&&i===3))?'done':''}">${x}</div>`).join('');
  $('#progress').innerHTML = d.task ? `<div class="busy"><span class="spinner"></span>${esc(d.task.progress)}<small>您可以稍后回来查看</small></div>` : d.failure ? `<div class="error">${esc(d.failure)} <button class="ghost" id="retry">重试处理</button></div>` : '';
  $('#retry')?.addEventListener('click', async () => {
    try {
      await api('/applications/' + d.id + '/retry', 'POST', {
        request_key: uid()
      });
      await poll()
    } catch (e) {
      failure(e)
    }
  });
  let html = messages(d);
  if (html !== lastMessage) {
    let el = $('#messages'),
      near = el.scrollHeight - el.scrollTop - el.clientHeight < 70;
    el.innerHTML = html;
    if (near || !lastMessage) el.scrollTop = el.scrollHeight;
    else $('#newmessages').hidden = false;
    lastMessage = html
  }
  let mh = materials(d);
  let mediaKey = JSON.stringify(d.media);
  if ($('#materials').dataset.mediaKey !== mediaKey) {
    $('#materials').dataset.mediaKey = mediaKey;
    $('#materials').innerHTML = mh;
    bindMedia(d)
  }
  $('#plan').innerHTML = planCard(d);
  $('#current-intent').textContent = d.intent;
  $('#agree')?.addEventListener('click', () => consent(d, true));
  $('#decline')?.addEventListener('click', () => consent(d, false));
  $('#composer').hidden = d.closed;
  $('#closed').hidden = !d.closed;
  $('#send').disabled = !!d.task || locked;
  $('#message').placeholder = d.task ? '门店正在处理，您可以先准备补充内容…' : '回复门店，或补充您想说的…'
}
async function consent(d, agree) {
  if (locked) return;
  locked = true;
  $('#agree')?.setAttribute('disabled', '');
  $('#decline')?.setAttribute('disabled', '');
  try {
    await api('/applications/' + d.id + '/consent', 'POST', {
      proposal_id: d.plan.id,
      agree,
      request_key: uid()
    });
    toast(agree ? '已收到您的确认' : '门店会根据您的意见调整方案');
    await poll();
    if (!agree) $('#message')?.focus()
  } catch (e) {
    failure(e)
  } finally {
    locked = false
  }
}
async function send(e) {
  e.preventDefault();
  if (locked || !selected) return;
  let text = $('#message').value.trim();
  if (!text && !files.files.length) return failure(new Error('请输入回复内容，或选择要补充的材料'));
  locked = true;
  $('#send').disabled = true;
  try {
    let uploads = await files.all(),
      payload = {
        text,
        uploads
      };
    await api('/applications/' + selected + '/messages', 'POST', {
      ...payload,
      request_key: key(payload)
    });
    $('#message').value = '';
    localStorage.removeItem('fresh-reply-' + selected);
    files.clear();
    pendingKey = null;
    $('#error').hidden = true;
    await poll()
  } catch (e) {
    failure(e)
  } finally {
    locked = false;
    if ($('#send')) $('#send').disabled = false
  }
}
let polling = false;
async function poll() {
  if (polling || !me) return;
  polling = true;
  try {
    if (selected) paint(await api('/applications/' + selected));
    else if (!location.hash) {
      let r = await api('/applications');
      let list = $('#list');
      if (list && r.applications.length) {
        let next = r.applications.map(caseCard).join('');
        if (list.innerHTML !== next) {
          list.innerHTML = next;
          bindCards()
        }
      }
    }
  } catch (e) {
    if (e.status === 401) {
      me = null;
      await shell()
    } else if (selected && $('#progress')) $('#progress').innerHTML = '<div class="hint">连接暂时中断，正在自动重新连接。您填写的内容会保留。</div>'
  } finally {
    polling = false
  }
}
