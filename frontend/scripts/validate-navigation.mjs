import assert from 'node:assert/strict';
import { bindComposedForms, composedFormPresentation } from '../src/js/retorna/composed-form.js';
import { bindNavigationSearch, matchesNavigation, searchShortcut } from '../src/js/retorna/navigation-search.js';
// Minimal DOM doubles exercise actual event handlers without a new dependency.
class Element {
  constructor() { this.dataset = {}; this.attrs = {}; this.events = {}; this.one = {}; this.many = {}; this.hidden = false; this.value = ''; }
  querySelector(s) { return this.one[s] ?? null; }
  querySelectorAll(s) { return this.many[s] ?? []; }
  setAttribute(k,v) { this.attrs[k] = v; }
  removeAttribute(k) { delete this.attrs[k]; }
  hasAttribute(k) { return k in this.attrs; }
  addEventListener(k,f) { (this.events[k] ??= []).push(f); }
  fire(k,e={}) { const event = { target:this, preventDefault(){this.prevented=true;}, stopPropagation(){}, ...e }; for(const f of this.events[k]??[]) f(event); return event; }
  focus() { document.activeElement = this; }
  click() { this.clicked = true; this.fire('click'); }
  closest() { return null; }
}
function setupForm(errors = []) {
  const doc = new Element(); doc.documentElement = { dataset: { retornaFormMode: 'all' } }; globalThis.document = doc;
  globalThis.requestAnimationFrame = callback => callback();
  const form = new Element(); form.attrs['data-form-sections'] = '';
  const steps = Array.from({length:3}, (_, i) => { const step = new Element(); step.dataset.stepLabel = `Seção ${i}`; if(errors.includes(i)) step.attrs['data-step-has-errors']=''; step.one['legend, [data-form-step-heading]']=new Element(); return step; });
  const controls = Array.from({length:3},()=>new Element());
  controls.forEach((control,i)=> { control.value=`valor ${i}`; control.validity={valid:true}; control.checkValidity=()=>control.validity.valid; control.closest=()=>steps[i]; control.reportValidity=()=> {control.reported=true;}; steps[i].querySelectorAll=()=>[control]; });
  const indicators = steps.map(()=>new Element()); const triggers = steps.map(()=>new Element());
  form.many['[data-form-step]']=steps; form.many['[data-form-step-indicator]']=indicators; form.many['[data-form-section-trigger]']=triggers;
  for(const s of ['list','status','previous','next']) form.one[`[data-form-step-${s}]`]=new Element();
  form.one['[data-form-final-submit]']=new Element();
  const summary = errors.length ? new Element() : null; form.one['[data-form-error-summary]']=summary;
  doc.many['[data-composed-form]']=[form];
  bindComposedForms();
  return {form,steps,controls,triggers,summary,next:form.one['[data-form-step-next]'],previous:form.one['[data-form-step-previous]'],submit:form.one['[data-form-final-submit]']};
}
assert.equal(composedFormPresentation('steps', 0, ['Acúmulo', 'Validade', 'Resgate'], [], true).statusText, 'Seção 1 de 3 — Acúmulo');
assert.equal(composedFormPresentation('steps', 0, ['Pessoa', 'Acesso']).statusText, 'Etapa 1 de 2 — Pessoa');
// Sections always expose the one submit; sequential wizards retain their final-step rule.
for (let index = 0; index < 3; index++) {
  for (const sections of [true, false]) {
    const state = composedFormPresentation('steps', index, ['A', 'B', 'C'], [], sections);
    assert.equal(state.submitHidden, !sections && index !== 2);
    assert.equal(state.submitDisabled, !sections && index !== 2);
    assert.equal(state.previousHidden, index === 0);
    assert.equal(state.nextHidden, index === 2);
  }
}
const sectionsForm = setupForm();
const uniqueSubmit = sectionsForm.submit;
for (let index = 0; index < 3; index++) {
  sectionsForm.triggers[index].click();
  assert.equal(sectionsForm.submit, uniqueSubmit);
  assert.equal(sectionsForm.submit.hidden, false);
  assert.equal(sectionsForm.submit.disabled, false);
}
// Saving from the first section opens/focuses the first invalid field elsewhere.
sectionsForm.triggers[0].click();
sectionsForm.controls[1].validity.valid = false;
sectionsForm.controls[2].validity.valid = false;
assert.equal(sectionsForm.submit.fire('click').prevented, true);
assert.equal(sectionsForm.steps[1].hidden, false);
assert.equal(document.activeElement, sectionsForm.controls[1]);
assert.equal(sectionsForm.controls[1].reported, true);
assert.equal(sectionsForm.submit.hidden, false);
sectionsForm.controls.forEach(control => { control.validity.valid = true; });
assert.equal(sectionsForm.submit.fire('click').prevented, undefined);
let f=setupForm();
assert.equal(f.form.one['[data-form-step-status]'].textContent, 'Seção 1 de 3 — Seção 0');
assert.deepEqual(f.steps.map(s=>s.hidden),[false,true,true]);
f.controls[0].validity.valid=false;
f.triggers[2].click();
assert.deepEqual(f.steps.map(s=>s.hidden),[true,true,false]);
assert.equal(f.submit.hidden,false);
assert.equal(f.next.hidden,true);
f.previous.click(); assert.equal(f.steps[1].hidden,false);
f.triggers[0].click(); f.next.click(); assert.equal(f.steps[1].hidden,false);
assert.deepEqual(f.controls.map(c=>c.value),['valor 0','valor 1','valor 2']);
f.triggers[2].click(); const submitEvent=f.submit.fire('click');
assert.equal(submitEvent.prevented,true); assert.equal(f.steps[0].hidden,false); assert.equal(document.activeElement,f.controls[0]);
f=setupForm([1,2]); assert.equal(f.steps[1].hidden,false); assert.equal(document.activeElement,f.summary);
assert.equal(f.triggers[1].attrs['aria-current'],'step');
const doc=new Element(); globalThis.document=doc;
const root=new Element(), panel=new Element(), trigger=new Element(), input=new Element(), status=new Element();
panel.hidden=true;
for(const [key,value] of Object.entries({panel,trigger,input,status})) root.one[`[data-navigation-search-${key}]`]=value;
const links=['Lojas','Configuração','Níveis'].map(label=> {const link=new Element();link.textContent=label;return link;});
const items=links.map(link=>{const item=new Element();item.one.a=link;return item;});
root.many['[data-navigation-search-item]']=items;
root.contains=e=>[root,panel,trigger,input,status,...links].includes(e);
doc.one['[data-navigation-search]']=root;
bindNavigationSearch();
doc.fire('keydown',{key:'k',altKey:true}); assert.equal(panel.hidden,false); assert.equal(doc.activeElement,input);
root.fire('keydown',{key:'ArrowDown',target:input}); assert.equal(doc.activeElement,links[0]);
root.fire('keydown',{key:'ArrowUp',target:links[0]}); assert.equal(doc.activeElement,links[2]);
doc.fire('keydown',{key:'k',altKey:true}); assert.equal(doc.activeElement,input);
input.value='config'; input.fire('input'); assert.deepEqual(items.map(i=>i.hidden),[true,false,true]);
root.fire('keydown',{key:'Enter',target:input}); assert.equal(links[1].clicked,true);
input.value='inexistente'; input.fire('input'); assert.equal(status.textContent,'Nenhum destino encontrado.');
root.fire('keydown',{key:'Escape'}); assert.equal(panel.hidden,true); assert.equal(doc.activeElement,trigger);
trigger.click(); doc.fire('click',{target:new Element()}); assert.equal(panel.hidden,true);
trigger.click(); root.fire('focusout',{relatedTarget:new Element()}); assert.equal(panel.hidden,true);
assert.equal(matchesNavigation('Níveis','NIV'),true);
assert.equal(searchShortcut({key:'k',altKey:true,ctrlKey:true}),false);
const editable=new Element(); editable.closest=()=>editable;
doc.fire('keydown',{key:'k',altKey:true,target:editable}); assert.equal(panel.hidden,true);
delete globalThis.document; delete globalThis.requestAnimationFrame;
console.log('Navegação direta, erros, valores, navegação auxiliar, busca e teclado: OK (DOM simulado).');
