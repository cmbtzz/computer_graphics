#version 330 core
in vec2 uv;
out vec4 fragColor;
uniform sampler2D image;
uniform float exposure;
void main() {
    vec3 c = texture(image, uv).rgb * exp2(exposure);
    // 对线性 HDR 累积结果做曝光、ACES 近似色调映射和 sRGB 编码。
    c = clamp((c * (2.51 * c + 0.03)) / (c * (2.43 * c + 0.59) + 0.14), 0.0, 1.0);
    c = mix(12.92 * c, 1.055 * pow(c, vec3(1.0 / 2.4)) - 0.055,
            step(vec3(0.0031308), c));
    fragColor = vec4(c, 1.0);
}
