#version 330 core
// 一个覆盖整个窗口的三角形；光线求交全部在片元着色器中完成。
out vec2 uv;
void main() {
    vec2 p = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
    uv = p;
    gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}
