import test from 'node:test';
import assert from 'node:assert/strict';
import {safeSourceUrl, latestForImage, analysisOf, referencesOf, latestReferences, canDraft, samePending, errorText} from '../web/ui-core.mjs';

test('source links reject scripts, files, credentials, relative paths and invalid values', () => {
  for (const value of ['javascript:alert(1)', 'data:text/html,x', 'file:///etc/passwd', '/.env.local', 'https://user:secret@example.com', undefined]) assert.equal(safeSourceUrl(value), null);
  assert.equal(safeSourceUrl('https://example.com/docs'), 'https://example.com/docs');
});
test('analysis follows selected image and excludes failed or pending runs', () => {
  const runs = [{id:'a',image_id:'one',kind:'analysis',status:'succeeded'},
    {id:'b',image_id:'two',kind:'analysis',status:'succeeded'},
    {id:'c',image_id:'one',kind:'analysis',status:'failed'},
    {id:'d',image_id:'one',kind:'analysis',status:'pending'}];
  assert.equal(latestForImage(runs, 'one', 'analysis').id, 'a');
  assert.equal(latestForImage(runs, 'missing', 'analysis'), undefined);
  assert.equal(runs[0].id, 'a');
});
test('agent analysis uses measured evidence and does not parse model prose', () => {
  const run = {kind:'agent',result:{citations:[{kind:'document'}, {kind:'analysis',score:19.48}]}};
  assert.equal(analysisOf(run).score, 19.48);
  assert.equal(analysisOf({kind:'agent',result:{answer:{claims:[{text:'score 100'}]}}}), null);
});
test('references display at most three saved results from either tool or agent', () => {
  const evidence = {kind:'image_references',matches:[1,2,3,4]};
  assert.deepEqual(referencesOf({result:{evidence:{r:evidence}}}), [1,2,3]);
  assert.deepEqual(referencesOf({result:{citations:[evidence]}}), [1,2,3]);
});
test('latest references stay with selected image', () => {
  const result = {citations:[{kind:'image_references',matches:[1]}]};
  const runs = [{id:'a',image_id:'one',status:'succeeded',result}, {id:'b',image_id:'two',status:'succeeded',result}];
  assert.equal(latestReferences(runs, 'one').id, 'a');
});
test('report requires successful answered agent run', () => {
  const run = {status:'succeeded',kind:'agent',result:{status:'answered',answer:{}}};
  assert.equal(canDraft(run), true);
  for (const status of ['failed','pending','running']) assert.equal(canDraft({...run,status}), false);
  assert.equal(canDraft({...run,result:{status:'needs_context',answer:{}}}), false);
  assert.equal(canDraft({...run,kind:'analysis'}), false);
});
test('pending guards follow kind and image', () => {
  const runs = [{kind:'analysis',image_id:'one',status:'running'}];
  assert.equal(samePending(runs,'analysis','one'), true);
  assert.equal(samePending(runs,'references','one'), false);
  assert.equal(samePending(runs,'analysis','two'), false);
});
test('unknown error messages do not echo raw provider content', () => {
  assert.equal(errorText('gsk_fake_secret'), '操作未完成，請重新整理後查看案件紀錄。');
  assert.match(errorText('rate_limited'), /免費額度/);
});

test('document-only runs never populate image panels without a selected image', () => {
  const run = {kind:'agent',image_id:null,status:'succeeded',result:{citations:[
    {kind:'analysis',score:99}, {kind:'image_references',matches:[1]}]}};
  assert.equal(latestForImage([run],null,'analysis'), undefined);
  assert.equal(latestReferences([run],null), undefined);
});
