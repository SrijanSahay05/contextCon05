// Grey particles flow left to right in straight lines past a dark ball.
// Near the ball, gravity takes over: close ones curve in and are swallowed,
// like a black hole. Time is in seconds, distances in CSS pixels.

const COUNT = 80
const PARTICLE = '161, 161, 166' // grey, as an rgb triple for per-particle alpha
const BALL = '#3a3a3c' // darker grey
const GRAVITY = 2_000_000 // pull strength (px³/s²)
const REACH = 7 // gravity only acts within REACH × ball radius

interface Particle {
  x: number
  y: number
  vx: number
  vy: number
  size: number
  alpha: number
}

export function createScoutField(ctx: CanvasRenderingContext2D) {
  let w = 0
  let h = 0
  let particles: Particle[] = []

  const ballR = () => Math.min(22, h * 0.08)

  const spawn = (x = -5): Particle => ({
    x,
    y: h * (0.15 + Math.random() * 0.7),
    vx: 110 + Math.random() * 150,
    vy: 0,
    size: 1.2 + Math.random() * 1.8,
    alpha: 0.35 + Math.random() * 0.5,
  })

  return {
    resize(width: number, height: number) {
      const first = w === 0
      w = width
      h = height
      if (first) particles = Array.from({ length: COUNT }, () => spawn(Math.random() * w))
    },

    step(dt: number) {
      const cx = w / 2
      const cy = h / 2
      const r0 = ballR()
      particles = particles.map((p) => {
        const dx = cx - p.x
        const dy = cy - p.y
        const r = Math.hypot(dx, dy)
        if (r < r0) return spawn() // swallowed
        if (r < r0 * REACH) {
          const a = GRAVITY / (r * r)
          p.vx += (a * dx * dt) / r
          p.vy += (a * dy * dt) / r
        }
        p.x += p.vx * dt
        p.y += p.vy * dt
        return p.x > w + 5 || p.y < -5 || p.y > h + 5 ? spawn() : p
      })
    },

    draw() {
      ctx.clearRect(0, 0, w, h)
      for (const p of particles) {
        ctx.fillStyle = `rgba(${PARTICLE}, ${p.alpha})`
        ctx.beginPath()
        ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2)
        ctx.fill()
      }
      ctx.fillStyle = BALL
      ctx.beginPath()
      ctx.arc(w / 2, h / 2, ballR(), 0, Math.PI * 2)
      ctx.fill()
    },
  }
}
