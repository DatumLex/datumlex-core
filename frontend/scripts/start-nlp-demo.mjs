import { createServer } from 'vite'
const server = await createServer({ server: { host: '127.0.0.1', port: 5180, strictPort: true, hmr: false, proxy: { '/api': 'http://127.0.0.1:8015' } } })
await server.listen()
console.log('FX115 DEMO: http://127.0.0.1:5180/nlp-demo.html — isolated synthetic backend on 8015')
