<script setup>
// Aurora 背景 —— 灵感来自 ReactBits 的 Aurora 动画背景（https://www.reactbits.dev/backgrounds/aurora）
// 实现：低分辨率 canvas 上绘制多个缓慢游走的径向渐变光团，CSS 大半径模糊成极光效果。
// 性能要点：canvas 只有视口 1/3 分辨率（反正要 blur），每帧 5 个径向渐变，几乎无开销。
import { onBeforeUnmount, onMounted, ref } from 'vue'

const canvasRef = ref(null)
let raf = 0

// 光团配色与深空主题呼应：电光青 / 青 / 靛 / 紫罗兰 / 深蓝
const BLOBS = [
  { color: '34,211,238', alpha: 0.30, size: 0.55, ox: 0.2, oy: 0.25, fx: 0.11, fy: 0.07, px: 0, py: 1.2 },
  { color: '20,184,166', alpha: 0.24, size: 0.50, ox: 0.85, oy: 0.30, fx: 0.07, fy: 0.10, px: 2.1, py: 0.4 },
  { color: '99,102,241', alpha: 0.26, size: 0.62, ox: 0.55, oy: 0.85, fx: 0.09, fy: 0.06, px: 4.0, py: 2.8 },
  { color: '139,92,246', alpha: 0.18, size: 0.45, ox: 0.15, oy: 0.75, fx: 0.12, fy: 0.08, px: 1.0, py: 3.3 },
  { color: '56,130,246', alpha: 0.20, size: 0.58, ox: 0.75, oy: 0.85, fx: 0.05, fy: 0.11, px: 5.2, py: 1.7 },
]

onMounted(() => {
  const canvas = canvasRef.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  const SCALE = 1 / 3 // 低分辨率 + CSS blur，性能远优于全分辨率绘制

  const resize = () => {
    canvas.width = Math.max(1, Math.round(window.innerWidth * SCALE))
    canvas.height = Math.max(1, Math.round(window.innerHeight * SCALE))
  }
  resize()
  window.addEventListener('resize', resize)

  const draw = now => {
    const t = now / 1000
    const { width: w, height: h } = canvas
    ctx.clearRect(0, 0, w, h)
    ctx.globalCompositeOperation = 'lighter'
    for (const b of BLOBS) {
      const x = w * (b.ox + 0.16 * Math.sin(t * b.fx * 2 + b.px))
      const y = h * (b.oy + 0.14 * Math.cos(t * b.fy * 2 + b.py))
      const r = Math.max(w, h) * b.size
      const g = ctx.createRadialGradient(x, y, 0, x, y, r)
      g.addColorStop(0, `rgba(${b.color},${b.alpha})`)
      g.addColorStop(1, 'rgba(0,0,0,0)')
      ctx.fillStyle = g
      ctx.fillRect(0, 0, w, h)
    }
    raf = requestAnimationFrame(draw)
  }

  // 尊重系统减少动态偏好：静态画一帧
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    draw(0)
    cancelAnimationFrame(raf)
    raf = 0
  } else {
    raf = requestAnimationFrame(draw)
  }

  onBeforeUnmount(() => {
    cancelAnimationFrame(raf)
    window.removeEventListener('resize', resize)
  })
})
</script>

<template>
  <canvas ref="canvasRef" class="aurora" aria-hidden="true" />
</template>

<style scoped>
.aurora {
  position: fixed;
  inset: 0;
  width: 100vw;
  height: 100vh;
  z-index: 0;
  pointer-events: none;
  filter: blur(72px) saturate(135%);
  opacity: 0.5;
}
</style>
