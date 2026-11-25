import assert from 'node:assert/strict';
import test from 'node:test';
import { JSDOM } from 'jsdom';
import { bindInstall } from '../../public/pwa.js';

test('the in-app install button keeps browser install UI available and handles an expired prompt', async () => {
  const dom = new JSDOM('<button data-install-app hidden>Install the app</button>');
  const { window } = dom;
  const button = window.document.querySelector('button');
  globalThis.document = window.document;
  try {
    bindInstall(window);
    const event = new window.Event('beforeinstallprompt', { cancelable: true });
    let prompts = 0;
    event.prompt = async () => {
      prompts += 1;
      throw new window.DOMException('The browser already used the prompt', 'InvalidStateError');
    };
    assert.equal(window.dispatchEvent(event), true);
    assert.equal(button.hidden, false);
    button.click();
    button.click();
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(prompts, 1);
    assert.equal(button.hidden, true);
  } finally {
    delete globalThis.document;
    window.close();
  }
});
