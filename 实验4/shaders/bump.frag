#version 330 core
in vec3 worldPosition, surfaceNormal, tangentU, tangentV;
in vec2 uv;
out vec4 fragColor;
uniform sampler2D heightMap;
uniform vec2 tiling;
uniform float bumpStrength, shininess, specularStrength;
uniform bool enableBump, tintByHeight;
uniform int displayMode;
uniform vec3 eye, lightPosition, materialColor;
uniform float lightPower;

vec3 encodeSRGB(vec3 c) {
    c = clamp(c, 0.0, 1.0);
    return mix(c * 12.92, 1.055 * pow(c, vec3(1.0 / 2.4)) - 0.055,
               step(vec3(0.0031308), c));
}

void main() {
    vec2 q = uv * tiling;
    float height = texture(heightMap, q).r;
    vec3 n = normalize(surfaceNormal);
    // 内壁、瓶底的法线已由几何生成器定向；从背面观察时将照明朝向观察侧。
    if (!gl_FrontFacing) n = -n;
    if (enableBump && bumpStrength != 0.0) {
        vec2 texel = 1.0 / vec2(textureSize(heightMap, 0));
        // 高度图是线性数据。中心差分求纹理高度导数，再用 tiling 应用链式法则。
        float hu = (texture(heightMap,q+vec2(texel.x,0)).r -
                    texture(heightMap,q-vec2(texel.x,0)).r) / (2.0*texel.x) * tiling.x;
        float hv = (texture(heightMap,q+vec2(0,texel.y)).r -
                    texture(heightMap,q-vec2(0,texel.y)).r) / (2.0*texel.y) * tiling.y;
        // 投影到切平面并解第一基本形式，避免 UV 拉伸或斜交基导致凹凸尺度错误。
        vec3 pu = tangentU - n*dot(n,tangentU);
        vec3 pv = tangentV - n*dot(n,tangentV);
        float a=dot(pu,pu), b=dot(pu,pv), c=dot(pv,pv);
        float determinant = a*c-b*b;
        if (determinant > 1e-10) {
            vec3 gradient = ((c*hu-b*hv)*pu + (a*hv-b*hu)*pv) / determinant;
            n = normalize(n - bumpStrength*gradient);
        }
    }
    if (displayMode == 1) {
        fragColor = vec4(n*.5+.5, 1.0);
        return;
    }
    if (displayMode == 2) {
        fragColor = vec4(vec3(height), 1.0);
        return;
    }
    vec3 l = normalize(lightPosition-worldPosition);
    vec3 v = normalize(eye-worldPosition);
    vec3 h = normalize(l+v);
    float diffuse = max(dot(n,l),0.0);
    float specular = diffuse > 0.0 ? pow(max(dot(n,h),0.0),shininess) : 0.0;
    vec3 color = materialColor;
    if (tintByHeight) color *= mix(.55,1.0,height);
    vec3 linearColor = color*(.10+lightPower*diffuse) +
                       vec3(1.0,.95,.86)*specularStrength*lightPower*specular;
    // 在全部光照计算之后，进行统一色调映射及显示编码。
    linearColor = linearColor/(vec3(1)+linearColor);
    fragColor = vec4(encodeSRGB(linearColor),1.0);
}
