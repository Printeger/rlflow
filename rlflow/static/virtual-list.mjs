// Display geometry only. Never mutates domain objects, counts or cursors.
export const ROW_HEIGHT = 64;
export function windowFor(length, scrollTop, viewportHeight, overscan = 4) {
  if (!Number.isSafeInteger(length) || length < 0 || !Number.isFinite(scrollTop) || !Number.isFinite(viewportHeight)) throw new TypeError('invalid geometry');
  const first = Math.min(length,Math.max(0,Math.floor(scrollTop / ROW_HEIGHT) - overscan));
  const end = Math.min(length, Math.max(first, Math.ceil((Math.max(0,scrollTop) + Math.max(0,viewportHeight)) / ROW_HEIGHT) + overscan));
  return {first,end,before:first * ROW_HEIGHT,after:(length-end) * ROW_HEIGHT};
}

export class VirtualList {
  constructor(box, renderRow, key) {
    this.box = box; this.renderRow = renderRow; this.key = key; this.items = []; this.timer = null;
    box.addEventListener('scroll',() => this.schedule(),{passive:true});
    box.addEventListener('keydown',event => this.keyboard(event));
    this.resize = new ResizeObserver(() => this.schedule()); this.resize.observe(box);
  }
  schedule() {
    if (this.timer !== null) return;
    this.timer = setTimeout(() => {this.timer = null;this.render();},34);
  }
  setItems(items) {
    const top = this.box.scrollTop, index = Math.floor(top / ROW_HEIGHT);
    const anchor = top >= 12 && this.items[index] ? this.key(this.items[index]) : null;
    this.items = items;
    if (anchor) {
      const next = items.findIndex(item => this.key(item) === anchor);
      this.box.scrollTop = next < 0 ? Math.min(top,Math.max(0,items.length * ROW_HEIGHT - this.box.clientHeight)) : next * ROW_HEIGHT + top % ROW_HEIGHT;
    } else this.box.scrollTop = 0;
    this.render();
  }
  render() {
    const focused = this.box.contains(document.activeElement) ? document.activeElement.dataset.virtualKey : null;
    const plan = windowFor(this.items.length,this.box.scrollTop,this.box.clientHeight);
    const spacer = height => {
      const node = document.createElement('div'); node.className = 'virtual-spacer';
      node.setAttribute('aria-hidden','true'); node.style.height = `${height}px`; return node;
    };
    const nodes = [spacer(plan.before)];
    for (let index = plan.first; index < plan.end; index++) {
      const node = this.renderRow(this.items[index]); node.dataset.virtualKey = this.key(this.items[index]);
      node.dataset.virtualIndex = String(index);
      node.setAttribute('aria-label',`${index+1} / ${this.items.length} · ${node.title || node.textContent}`); nodes.push(node);
    }
    nodes.push(spacer(plan.after)); this.box.replaceChildren(...nodes);
    if (focused) {
      const node = nodes.find(node => node.dataset.virtualKey === focused);
      if (node) node.focus({preventScroll:true}); else this.box.focus({preventScroll:true});
    }
  }
  keyboard(event) {
    if (!['ArrowDown','ArrowUp','Home','End'].includes(event.key) || !this.items.length) return;
    event.preventDefault();
    const current = Number(document.activeElement.dataset.virtualIndex ?? Math.floor(this.box.scrollTop/ROW_HEIGHT));
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? this.items.length-1 : Math.max(0,Math.min(this.items.length-1,current+(event.key === 'ArrowDown' ? 1 : -1)));
    if (next * ROW_HEIGHT < this.box.scrollTop) this.box.scrollTop = next * ROW_HEIGHT;
    else if ((next+1)*ROW_HEIGHT > this.box.scrollTop+this.box.clientHeight) this.box.scrollTop = (next+1)*ROW_HEIGHT-this.box.clientHeight;
    this.render();
    [...this.box.children].find(node => node.dataset.virtualIndex === String(next))?.focus({preventScroll:true});
  }
}
