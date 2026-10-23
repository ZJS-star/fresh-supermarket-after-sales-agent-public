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
  errorBox
} from './shared.js';
let me = await shell(),
  selected = null,
  filter = 'all',
  sort = 'new',
  query = '',
  latest = null,
  locked = false,
  lastOps = '',
  lastMessages = '',
  polling = false;
if (me) {
  $('#app').innerHTML = `<div class="merchant-shell"><nav class="sidebar"><div class="eyebrow" style="padding:0 14px">WORKSPACE</div><div class="navitem">▤　售后工作台</div><p>青禾鲜选 · 邻里店<br>08:00 – 21:00</p><div class="divider"></div><p>统一接待 · 及时响应<br>所有操作均为模拟处理</p></nav><div class="workbench"><div class="row"><div><div class="eyebrow">AFTER-SALES SERVICE</div><h1>让每一份售后，都有着落。</h1></div><button class="secondary" id="refresh">刷新</button></div><div class="statgrid" id="stats"></div><div class="workgrid" id="workgrid"><section class="worklist"><div class="searchrow"><input id="search" placeholder="搜索售后编号或商品" aria-label="搜索售后编号或商品"><select id="sort" aria-label="时间排序"><option value="new">最近提交</option><option value="old">最早提交</option></select></div><div class="filters" id="filters"></div><div id="list"></div></section><section class="workdetail" id="detail"><div class="card empty"><div style="font-size:34px">▤</div><h2>选择一份申请，开始接待</h2><p>订单、材料、核验摘要与处理方案会集中显示在这里。</p></div></section></div></div></div>`;
  $('#refresh').onclick = poll;
  $('#search').oninput = e => {
    query = e.target.value;
    loadList()
  };
  $('#sort').onchange = e => {
    sort = e.target.value;
    loadList()
  };
  await poll();
  if (location.hash) open(location.hash.slice(1));
  setInterval(poll, 1500)
}
async function loadList() {
  let r = await api('/applications');
  $('#stats').innerHTML = [
    ['pending', '待处理'],
    ['review', '待审核'],
    ['customer', '待顾客补充'],
    ['completed', '已完成']
  ].map(([k, t]) => `<div class="stat"><small>${t}</small><strong>${r.counts[k]}</strong></div>`).join('');
  $('#filters').innerHTML = [
    ['all', '全部'],
    ['pending', '待处理'],
    ['review', '待审核'],
    ['customer', '待顾客'],
    ['completed', '已完成']
  ].map(([k, t]) => `<button class="${filter===k?'active':''}" data-filter="${k}">${t}</button>`).join('');
  document.querySelectorAll('[data-filter]').forEach(b => b.onclick = () => {
    filter = b.dataset.filter;
    loadList()
  });
  let rows = r.applications.filter(d => (filter === 'all' || d.category === filter) && (!query || (d.number + ' ' + (d.item?.name || '') + ' ' + d.description).includes(query)));
  if (sort === 'old') rows.reverse();
  let html = rows.map(d => caseCard(d).replace('card clickable', 'card clickable' + (d.id === selected ? ' selected' : ''))).join('') || '<div class="empty"><p>这里还没有申请</p><small>顾客提交后会自动出现在列表中。</small></div>';
  if ($('#list').innerHTML !== html) {
    $('#list').innerHTML = html;
    document.querySelectorAll('[data-open]').forEach(el => el.onclick = () => open(el.dataset.open))
  }
}
async function open(id) {
  try {
    let d = await api('/applications/' + id);
    selected = id;
    latest = d;
    lastOps = '';
    lastMessages = '';
    location.hash = id;
    $('#workgrid').classList.add('selected');
    $('#detail').innerHTML = `<button class="ghost back" id="back">← 返回列表</button><section class="card"><div class="row"><div><div class="eyebrow">${esc(d.number)}</div><h2>售后接待</h2></div><div id="status"></div></div>${product(d)}<div class="case-description" style="display:block">${esc(d.description)}</div><small>诉求：${esc(d.intent)}　·　提交于 ${date(d.created)}</small><div class="divider"></div><h3>订单与商品</h3><div id="order"></div></section><section class="card"><h2>当前处理</h2>${errorBox()}<div id="progress"></div><div id="ops"></div></section><section class="card"><div class="section-title"><h2>材料与核验摘要</h2><small>需门店判断</small></div><div id="materials"></div><div id="findings" style="margin-top:18px"></div></section><section class="card" id="plan"></section><section class="card"><h2>沟通记录</h2><div class="messages" id="messages"></div><form id="reply" class="composer"><textarea id="message" aria-label="门店回复" placeholder="接待并回复顾客…"></textarea><p class="hint">发送门店回复将接管沟通，自动服务会停止对外回复。</p><div class="actions"><button id="send">接待并发送</button></div></form></section><section class="card"><h2>处理时间线</h2><div id="timeline"></div></section><details class="card technical"><summary>技术详情 · 实际核验与工具记录</summary><p class="hint">仅商家可见；离线测试和真实模型分别标记。顾客看不到这些内部记录。</p><pre id="technical"></pre></details>`;
    $('#back').onclick = () => {
      $('#workgrid').classList.remove('selected');
      selected = null;
      location.hash = ''
    };
    $('#reply').onsubmit = async e => {
      e.preventDefault();
      let text = $('#message').value.trim();
      if (!text) return failure(new Error('请先填写回复内容'));
      await perform('/messages', {
        text
      }, () => {
        $('#message').value = ''
      })
    };
    paint(d);
    loadList()
  } catch (e) {
    toast(e.message)
  }
}

function paint(d) {
  if (selected !== d.id) return;
  latest = d;
  $('#status').innerHTML = statusCard(d);
  $('#order').innerHTML = d.item ? `<ul class="specs"><li><span>购买订单</span><span>${esc(d.item.order_id)}</span></li><li><span>商品规格</span><span>${esc(d.item.spec)}</span></li><li><span>购买数量 / 实付</span><span>${d.item.quantity} ${unit(d.item.unit)} / ¥${yuan(d.item.paid_cents)}</span></li><li><span>可继续处理</span><span>${d.history?.remaining_quantity??'待核实'} ${unit(d.item.unit)} / ¥${yuan(d.history?.remaining_cents||0)}</span></li></ul>` : '<p class="hint">顾客未找到订单。先核对购买线索，证据不足时可安排检查或人工处理。</p>';
  let mh = materials(d);
  let mediaKey = JSON.stringify(d.media);
  if ($('#materials').dataset.mediaKey !== mediaKey) {
    $('#materials').dataset.mediaKey = mediaKey;
    $('#materials').innerHTML = mh;
    bindMedia(d)
  }
  let findings = d.internal.findings || [];
  $('#findings').innerHTML = findings.length ? findings.slice(-5).map(f => `<p style="font-size:13px;line-height:1.7"><strong>${esc(({visual_observation:'视觉观察（待复核）',customer_claim:'顾客陈述',unknown:'尚未确认'})[f.source_type]||'材料观察')}</strong> ${esc(f.statement||f.fact||f.observation||f.text||'观察内容待复核')}</p>`).join('') : '<p class="hint">暂无独立视觉结论。请结合顾客描述和材料判断，气味及异常原因不能仅凭外观确认。</p>';
  if (d.internal.unresolved?.length) $('#findings').innerHTML += `<div class="notice">待核实：${d.internal.unresolved.map(esc).join('；')}</div>`;
  $('#plan').innerHTML = planCard(d, true);
  let html = messages(d);
  if (html !== lastMessages) {
    let box = $('#messages'),
      near = box.scrollHeight - box.scrollTop - box.clientHeight < 70;
    box.innerHTML = html;
    if (near || !lastMessages) box.scrollTop = box.scrollHeight;
    lastMessages = html
  }
  $('#reply').hidden = d.closed;
  $('#send').disabled = locked;
  $('#progress').innerHTML = d.task ? `<div class="busy"><span class="spinner"></span>${esc(d.task.progress)}</div>` : d.failure ? `<div class="error">${esc(d.failure)}</div>` : '';
  let opkey = JSON.stringify([d.closed, d.task?.id, d.plan, d.manual, d.status]);
  if (lastOps !== opkey) {
    lastOps = opkey;
    $('#ops').innerHTML = operations(d);
    bindOps(d)
  }
  $('#timeline').innerHTML = d.timeline.length ? d.timeline.map(t => `<p style="font-size:13px">${esc(t.text)}<br><small>${date(t.time)}</small></p>`).join('') : '<p class="hint">申请已接收，等待后续处理。</p>';
  $('#technical').textContent = JSON.stringify({
    mode: d.internal.mode,
    raw_status: d.internal.status,
    proposal_id: d.plan?.id,
    model_seconds: d.internal.model_seconds,
    model_calls: d.internal.model_calls,
    purchase_verification: d.internal.verified_facts,
    findings: d.internal.findings,
    tool_events: d.internal.events.filter(e => ['tool', 'staff', 'host'].includes(e.role)),
    jobs: d.internal.jobs
  }, null, 2)
}

function operations(d) {
  if (d.task) return '<p class="hint">请求已受理，处理完成后会自动更新。</p>' + (!d.manual ? '<button data-op="takeover">接管沟通</button>' : '');
  if (d.closed) return '<p class="notice">本次申请已处理结束，记录与材料已保留。</p>';
  let p = d.plan,
    main = '';
  if (p?.consent === 'agreed' && p.stage === '待门店处理') {
    if (p.type === 'exchange_proposal' && !p.stock_confirmed) main = '<button data-op="confirm_stock">核对并确认库存</button>';
    else main = `<button data-op="${{refund_proposal:'approve_refund',exchange_proposal:'approve_exchange',store_inspection:'confirm_inspection'}[p.type]}">${{refund_proposal:'审核并模拟退款',exchange_proposal:'确认并模拟换货',store_inspection:'确认到店安排'}[p.type]}</button>`
  } else if (!d.manual) main = '<button data-op="takeover">接管沟通</button>';
  return `<div class="gap">${main}<button class="secondary" id="edit">${p?'修改处理方案':'拟定处理方案'}</button></div><p class="hint">${p?.needs_confirmation?'当前版本待顾客确认，确认前不能执行。':d.manual?'本申请由门店接待，自动服务已停止对外回复。':'门店审核与执行均为本地模拟。'}</p><details><summary class="technical">取消或结束申请</summary><label>处理说明<textarea id="close-note" placeholder="请说明处理结果或取消原因"></textarea></label><button class="danger" data-op="close_manual">结束并保留记录</button></details>`
}

function bindOps(d) {
  document.querySelectorAll('[data-op]').forEach(b => b.onclick = async () => {
    let operation = b.dataset.op,
      note = $('#close-note')?.value || '';
    if (operation === 'close_manual' && !note.trim()) return failure(new Error('请填写处理说明'));
    await perform('/actions', {
      proposal_id:d.plan?.id||null,
      operation,
      note
    })
  });
  $('#edit')?.addEventListener('click', () => edit(d))
}
async function perform(path, payload, after) {
  if (locked) return;
  locked = true;
  document.querySelectorAll('[data-op],#send').forEach(b => b.disabled = true);
  try {
    await api('/applications/' + selected + path, 'POST', {
      ...payload,
      request_key: uid()
    });
    after?.();
    toast('操作已受理，处理结果会自动同步');
    await poll()
  } catch (e) {
    failure(e)
  } finally {
    locked = false;
    document.querySelectorAll('[data-op],#send').forEach(b => b.disabled = false)
  }
}

function edit(d) {
  let dialog = document.createElement('dialog');
  dialog.innerHTML = `<h2>${d.plan?'修改处理方案':'拟定处理方案'}</h2><p class="hint">保存后需顾客重新确认。本次操作会由门店接管沟通。</p><p class="error" id="editerror" hidden></p><form id="editform"><label>方案类型<select id="type" aria-label="方案类型"><option value="store_inspection">到店检查</option><option value="refund_proposal" ${!d.item?'disabled':''}>退款</option><option value="exchange_proposal" ${!d.item?'disabled':''}>换货</option></select></label><label id="qtylabel">处理数量（${unit(d.item?.unit)}）<input type="number" id="quantity" min="1" step="1" value="${d.plan?.quantity||1}"></label><label id="amountlabel">退款金额（元）<input id="amount" inputmode="decimal" placeholder="按数量自动核算" readonly></label><p class="hint" id="quote"></p><label id="appointmentlabel">预计到店日期与时间<input id="appointment" type="datetime-local" step="1800"></label><label>待核实事项<textarea id="uncertainties" placeholder="例如：异常范围及原因需要检查"></textarea></label><div class="actions"><button type="button" class="secondary" id="cancel-edit">返回</button><button id="save">保存并请顾客确认</button></div></form>`;
  document.body.append(dialog);
  dialog.showModal();
  $('#type').value = d.plan?.type || 'store_inspection';
  if (d.plan?.appointment) $('#appointment').value = d.plan.appointment.slice(0, 16);
  $('#cancel-edit').onclick = () => dialog.remove();
  let quoteTimer;
  async function fields() {
    let type = $('#type').value;
    $('#qtylabel').hidden = type === 'store_inspection';
    $('#amountlabel').hidden = type !== 'refund_proposal';
    $('#appointmentlabel').hidden = type === 'refund_proposal';
    $('#quote').textContent = '';
    if (type === 'refund_proposal') {
      clearTimeout(quoteTimer);
      quoteTimer = setTimeout(async () => {
        try {
          let q = await api('/applications/' + d.id + '/quote?quantity=' + $('#quantity').value);
          $('#amount').value = Number(q.amount_yuan).toFixed(2);
          $('#quote').textContent = '已按优惠分摊和历史处理核算，金额由后台校验。'
        } catch (e) {
          $('#quote').textContent = e.message
        }
      }, 250)
    }
  }
  $('#type').onchange = fields;
  $('#quantity').oninput = fields;
  fields();
  $('#editform').onsubmit = async e => {
    e.preventDefault();
    $('#save').disabled = true;
    try {
      let payload = {
        type: $('#type').value,
        quantity: $('#type').value === 'store_inspection' ? 0 : Number($('#quantity').value),
        appointment: $('#appointment').value || null,
        uncertainties: $('#uncertainties').value
      };
      await api('/applications/' + selected + '/proposal', 'POST', {
        ...payload,
        request_key: uid()
      });
      dialog.remove();
      toast('修改请求已受理，结果将在处理区更新');
      await poll()
    } catch (e) {
      failure(e, '#editerror');
      $('#save').disabled = false
    }
  }
}
async function poll() {
  if (polling || !me) return;
  polling = true;
  try {
    await loadList();
    if (selected) paint(await api('/applications/' + selected))
  } catch (e) {
    if (e.status === 401) {
      me = null;
      await shell()
    } else toast('连接暂时中断，正在自动重新连接')
  } finally {
    polling = false
  }
}
