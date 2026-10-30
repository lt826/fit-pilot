import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
// Element Plus 深色主题变量（必须在 index.css 之后引入才能覆盖）
import 'element-plus/theme-chalk/dark/css-vars.css'
import App from './App.vue'

// 深色主题开关：挂 html.dark 后 Element 变量组整体切换
document.documentElement.classList.add('dark')

createApp(App).use(ElementPlus).mount('#app')
