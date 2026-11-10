'use strict';
(() => {
  const $ = id => document.getElementById(id);
  let currentUser = null;
  const help = '다른 기기 또는 비밀번호 관리자에 저장한 패스키를 확인해 주세요. 등록된 패스키를 모두 분실했다면 이 서비스에서는 계정을 복구할 수 없습니다.';
  function message(text, error = false) {
    $('pk-message').textContent = text;
    $('pk-message').classList.toggle('pk-error', error);
  }
  async function api(path, method = 'GET', body) {
    const response = await fetch(path, {
      method, credentials: 'same-origin', cache: 'no-store',
      headers: body ? {'Content-Type': 'application/json'} : {},
      body: body ? JSON.stringify(body) : undefined
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(typeof data.detail === 'string' ? data.detail : '입력 내용을 확인해 주세요.');
    }
    return data;
  }
  function from64(value) {
    const text = value.replace(/-/g, '+').replace(/_/g, '/');
    return Uint8Array.from(atob(text + '='.repeat((4 - text.length % 4) % 4)), c => c.charCodeAt(0));
  }
  function to64(value) {
    if (value == null) return null;
    return btoa(String.fromCharCode(...new Uint8Array(value))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }
  function creationOptions(options) {
    return {...options, challenge: from64(options.challenge),
      user: {...options.user, id: from64(options.user.id)},
      excludeCredentials: (options.excludeCredentials || []).map(c => ({...c, id: from64(c.id)}))};
  }
  function requestOptions(options) {
    return {...options, challenge: from64(options.challenge),
      allowCredentials: (options.allowCredentials || []).map(c => ({...c, id: from64(c.id)}))};
  }
  function credentialJSON(credential) {
    if (!credential) throw new Error('패스키 선택이 취소되었습니다.');
    const r = credential.response;
    const response = {clientDataJSON: to64(r.clientDataJSON)};
    if (r.attestationObject) {
      response.attestationObject = to64(r.attestationObject);
      response.transports = r.getTransports ? r.getTransports() : [];
    } else {
      response.authenticatorData = to64(r.authenticatorData);
      response.signature = to64(r.signature);
      response.userHandle = to64(r.userHandle);
    }
    return {id: credential.id, rawId: to64(credential.rawId), type: credential.type,
      response, clientExtensionResults: credential.getClientExtensionResults()};
  }
  function element(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  }
  function date(value) {
    return new Date(value).toLocaleDateString('ko-KR');
  }
  async function refresh() {
    $('pk-private').replaceChildren();
    $('pk-keys').replaceChildren();
    currentUser = (await api('/api/me')).user;
    $('pk-name-row').hidden = !!currentUser;
    $('pk-name').required = !currentUser;
    $('pk-login').hidden = !!currentUser;
    $('pk-logout').hidden = !currentUser;
    $('pk-manage').hidden = !currentUser;
    $('pk-register').textContent = currentUser ? '패스키 추가' : '첫 패스키 등록';
    $('pk-state').textContent = currentUser ? `${currentUser.display_name}님의 비공개 공간` : '패스키로 본인만 열 수 있는 비공개 공간입니다.';
    $('pk-locked').hidden = !!currentUser;
    if (!currentUser) return;
    const [records, keys] = await Promise.all([api('/api/private/items'), api('/api/passkeys')]);
    for (const item of records.items) {
      const article = element('article', undefined, 'card');
      article.append(element('p', `${date(item.record_date)} · 과제용 가상 기록`, 'eyebrow'),
        element('h3', item.title), element('p', item.body, 'short'));
      $('pk-private').append(article);
    }
    for (const key of keys.passkeys) {
      const row = element('li', undefined, 'pk-key');
      const info = element('div');
      info.append(element('strong', key.name), element('p', `${key.provider_note || '저장 위치 메모 없음'} · 등록 ${date(key.created_at)}`));
      const button = element('button', '삭제', 'pk-button pk-secondary');
      button.type = 'button';
      button.disabled = keys.passkeys.length <= 1;
      if (button.disabled) button.title = '마지막 패스키입니다. 먼저 다른 패스키를 추가해 주세요.';
      button.addEventListener('click', () => act(async () => {
        if (!confirm(`‘${key.name}’ 패스키의 사이트 등록을 삭제할까요?`)) return;
        await api(`/api/passkeys/${key.id}`, 'DELETE');
        await refresh();
        message('삭제했습니다. 이 패스키로는 더 이상 로그인할 수 없습니다.');
      }));
      row.append(info, button); $('pk-keys').append(row);
    }
  }
  async function act(work) {
    const buttons = [...document.querySelectorAll('#passkey-area button')];
    const states = buttons.map(button => button.disabled);
    buttons.forEach(button => button.disabled = true);
    try { await work(); }
    catch (error) {
      const cancelled = error.name === 'NotAllowedError' || error.name === 'AbortError';
      message(cancelled ? `인증이 취소되었거나 시간이 초과되었습니다. ${help}` : error.message, true);
    } finally {
      buttons.forEach((button, i) => { if (button.isConnected) button.disabled = states[i]; });
    }
  }
  $('pk-register-form').addEventListener('submit', event => {
    event.preventDefault();
    act(async () => {
      const display_name = currentUser ? currentUser.display_name : $('pk-name').value.trim();
      const name = $('pk-key-name').value.trim();
      if (!display_name || !name) throw new Error('이름과 패스키 이름을 입력해 주세요.');
      message('기기에서 패스키를 생성하고 확인해 주세요.');
      const flow = await api('/api/passkeys/register/options', 'POST', {display_name});
      const credential = await navigator.credentials.create({publicKey: creationOptions(flow.options)});
      await api('/api/passkeys/register/verify', 'POST', {flow_id: flow.flow_id,
        credential: credentialJSON(credential), display_name, name,
        provider_note: $('pk-provider').value.trim()});
      await refresh();
      $('pk-key-name').value = ''; $('pk-provider').value = '';
      message('패스키를 등록했습니다. 비공개 기록을 확인할 수 있습니다.');
    });
  });
  $('pk-login').addEventListener('click', () => act(async () => {
    message('등록한 패스키를 선택해 주세요.');
    const flow = await api('/api/passkeys/login/options', 'POST', {});
    const credential = await navigator.credentials.get({publicKey: requestOptions(flow.options)});
    await api('/api/passkeys/login/verify', 'POST', {flow_id: flow.flow_id, credential: credentialJSON(credential)});
    await refresh(); message('패스키로 로그인했습니다.');
  }));
  $('pk-logout').addEventListener('click', () => act(async () => {
    await api('/api/logout', 'POST', {});
    await refresh(); message('로그아웃했습니다.');
  }));
  window.addEventListener('pageshow', () => {
    if (!window.PublicKeyCredential || !window.isSecureContext) {
      message('패스키를 지원하는 브라우저에서 HTTPS 주소로 접속해 주세요.', true);
      $('pk-register').disabled = true; $('pk-login').disabled = true;
      return;
    }
    refresh().catch(error => message(error.message, true));
  });
  window.addEventListener('pagehide', () => {
    $('pk-private').replaceChildren();
    $('pk-keys').replaceChildren();
  });
  if (location.hostname === 'localhost') {
    $('pk-development').hidden = false;
  }
})();
