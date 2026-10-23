import {
  $,
  esc,
  api,
  shell,
  toast,
  failure,
  date,
  errorBox
} from './shared.js';
let me = await shell();
if (me) {
  await render();
  setInterval(update, 3000)
}
async function render() {
  let d = await api('/console');
  $('#app').innerHTML = `<div class="console"><div class="eyebrow">DEMO LAUNCHER</div><h1>准备好，一起演示。</h1><p class="muted">真实业务空间与评测运行分开。顾客自主提交，门店统一接待。</p>${errorBox()}<div class="console-grid"><section class="card"><h2>进入角色</h2><p class="hint">预置身份仅用于本地演示。双端会话独立，可同时打开。</p><div class="gap"><button id="customer">顾客小林 ↗</button><button class="secondary" id="merchant">门店客服 ↗</button><button class="ghost" id="other">顾客小陈 ↗</button></div><div class="divider"></div><h3>模拟购买记录</h3><p class="hint">小林：榴莲、葡萄与西瓜；包含一单多商品。葡萄当前缺货。小陈使用独立订单，数据访问相互隔离。</p><h3>可选演示素材</h3><p class="hint">公开版商品样例是代码生成的占位图，不代表真实商品或异常。视觉联调请上传自己的商品图片；小票按模拟订单生成。</p>${d.sample_materials.map(m=>`<a href="${m.url}" download>${esc(m.label)} ↓</a>`).join('')}</section><section class="card"><h2>运行环境</h2><div id="environment"></div><div class="divider"></div><h3>预置案件测试</h3><p class="hint">私有评测素材和标准答案不随公开版分发。此入口保留工具协议，案例列表为空；交互演示请使用顾客端。</p><a href="/dev-console" target="_blank">打开预置案件控制台 ↗</a><h3 style="margin-top:22px">重置演示空间</h3><p class="hint">生成新的模拟业务库和会话。旧空间、工单、上传材料和真实运行记录保留归档；存在进行中任务时拒绝重置。</p><button class="danger" id="reset">重置并保留历史</button><div id="reset-confirm" hidden class="notice">当前身份会退出，新空间将恢复预置订单。<button class="danger" id="confirm-reset">确认重置</button><button class="ghost" id="cancel-reset">返回</button></div></section></div><section class="card"><h2>后台任务与故障</h2><p class="hint">任务串行处理同一申请；实际事件驱动进度，不提供虚构百分比。</p><div id="tasks"></div></section><p class="hint">已有真实运行与本轮实时记录分别保存；离线软件测试明确标记，不作为模型成绩。</p></div>`;
  $('#customer').onclick = () => enter('customer', '/');
  $('#merchant').onclick = () => enter('merchant', '/staff');
  $('#other').onclick = () => enter('other', '/');
  $('#reset').onclick = () => $('#reset-confirm').hidden = false;
  $('#cancel-reset').onclick = () => $('#reset-confirm').hidden = true;
  $('#confirm-reset').onclick = async () => {
    try {
      await api('/console/reset', 'POST', {});
      toast('新空间已准备，历史记录已归档');
      location.reload()
    } catch (e) {
      failure(e)
    }
  };
  paint(d)
}
async function enter(account, path) {
  try {
    await api('/login', 'POST', {
      account
    });
    window.open(path, '_blank')
  } catch (e) {
    failure(e)
  }
}

function paint(d) {
  $('#environment').innerHTML = `<ul class="specs"><li><span>模型配置</span><span>${d.model_configured?'已配置':'未配置'}</span></li><li><span>模型</span><span>${esc(d.model||'—')}</span></li><li><span>运行模式</span><span>${esc(d.mode)}</span></li><li><span>场景时间</span><span>${date(d.scenario_time)}</span></li><li><span>归档空间</span><span>${d.archives.length} 个</span></li></ul><p class="hint">配置就绪不等于已验证连通。任务失败原因显示于下方。</p>`;
  $('#tasks').innerHTML = d.tasks.length ? d.tasks.map(t => `<div style="padding:13px 0;border-bottom:1px solid var(--border);font-size:12px"><span class="status">${esc(t.status)}</span> <span>${esc(t.application.slice(0,8))} · ${date(t.updated)}</span>${t.error?`<pre>${esc(t.error)}</pre>`:''}</div>`).join('') : '<div class="empty">还没有后台任务。从顾客端发起一份申请开始。</div>'
}
async function update() {
  try {
    paint(await api('/console'))
  } catch {}
}
