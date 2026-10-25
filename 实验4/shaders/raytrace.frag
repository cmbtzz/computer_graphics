#version 330 core
in vec2 uv;
out vec4 fragColor;
uniform vec2 resolution;
uniform int shadowSamples;
uniform vec3 eye, target;
uniform float fieldOfView;
uniform int objectCount;
// shape: 0 球，1 轴对齐盒，2 Y 轴封闭圆柱。
uniform int shape[16];
uniform vec3 center[16], extent[16], baseColor[16];
uniform vec4 material[16]; // 镜面反射率、透射比例、折射率、高光指数
uniform int pattern[16]; // 0 纯色，1 棋盘，2 程序化木纹
uniform vec3 lightPosition, lightColor;
uniform float lightPower, lightSize, ambientLight, rayEpsilon;
uniform int maxDepth;
uniform bool useReflection, useRefraction, useShadows, softShadows;
const float FAR = 1e20;
const int LIGHT_ID = 5;

// 固定的低差异点列，全部在当前帧内计算，不随时间改变以避免闪烁。
float radicalInverse(int value) {
    float result = 0.0, factor = 0.5;
    for (int bit = 0; bit < 5; ++bit) {
        result += float(value & 1) * factor;
        value >>= 1;
        factor *= 0.5;
    }
    return result;
}

// 球的二次方程保留两个根，原点在球内时选择正的出射根。
float sphereHit(vec3 o, vec3 d, vec3 c, float r, out vec3 n) {
    vec3 p = o - c;
    float b = dot(p, d), h = b * b - dot(p, p) + r * r;
    if (h < 0.0) return FAR;
    float t = -b - sqrt(h);
    if (t < rayEpsilon) t = -b + sqrt(h);
    if (t < rayEpsilon) return FAR;
    n = normalize(p + t * d);
    return t;
}

// slab 求交显式处理平行射线，避免 0 * infinity 产生 NaN。
float boxHit(vec3 o, vec3 d, vec3 c, vec3 e, out vec3 n) {
    vec3 p = o - c, nearNormal = vec3(0), farNormal = vec3(0);
    float lo = -FAR, hi = FAR;
    for (int axis = 0; axis < 3; ++axis) {
        if (abs(d[axis]) < 1e-8) {
            if (abs(p[axis]) > e[axis]) return FAR;
        } else {
            float a = (-e[axis] - p[axis]) / d[axis];
            float b = ( e[axis] - p[axis]) / d[axis];
            vec3 na = vec3(0), nb = vec3(0);
            na[axis] = -1.0; nb[axis] = 1.0;
            if (a > b) { float q = a; a = b; b = q; vec3 v = na; na = nb; nb = v; }
            if (a > lo) { lo = a; nearNormal = na; }
            if (b < hi) { hi = b; farNormal = nb; }
            if (lo > hi) return FAR;
        }
    }
    if (hi < rayEpsilon) return FAR;
    if (lo >= rayEpsilon) { n = nearNormal; return lo; }
    n = farNormal; return hi;
}

float cylinderHit(vec3 o, vec3 d, vec3 c, vec3 e, out vec3 n) {
    vec3 p = o - c;
    float result = FAR, a = dot(d.xz, d.xz);
    float b = dot(p.xz, d.xz), h = b * b - a * (dot(p.xz, p.xz) - e.x * e.x);
    if (a > 1e-8 && h >= 0.0) {
        for (int root = 0; root < 2; ++root) {
            float t = (-b + (root == 0 ? -sqrt(h) : sqrt(h))) / a;
            if (t >= rayEpsilon && t < result && abs(p.y + t * d.y) <= e.y) {
                result = t; n = normalize(vec3(p.x + t*d.x, 0, p.z + t*d.z));
            }
        }
    }
    if (abs(d.y) > 1e-8) {
        for (int cap = 0; cap < 2; ++cap) {
            float signY = cap == 0 ? -1.0 : 1.0;
            float t = (signY * e.y - p.y) / d.y;
            vec2 q = p.xz + t * d.xz;
            if (t >= rayEpsilon && t < result && dot(q,q) <= e.x*e.x) {
                result = t; n = vec3(0, signY, 0);
            }
        }
    }
    return result;
}

int intersectScene(vec3 o, vec3 d, out float distance, out vec3 normal) {
    distance = FAR;
    int hit = -1;
    for (int i = 0; i < objectCount; ++i) {
        vec3 n;
        float t;
        if (shape[i] == 0) t = sphereHit(o, d, center[i], extent[i].x, n);
        else if (shape[i] == 1) t = boxHit(o, d, center[i], extent[i], n);
        else t = cylinderHit(o, d, center[i], extent[i], n);
        if (t < distance) { distance = t; normal = n; hit = i; }
    }
    return hit;
}

vec3 surfaceColor(int id, vec3 p) {
    vec3 c = baseColor[id];
    if (pattern[id] == 1) {
        float tile = mod(floor(p.x * 1.1) + floor(p.z * 1.1), 2.0);
        c *= mix(0.32, 1.0, tile);
    } else if (pattern[id] == 2) {
        vec3 q = p - center[id];
        float grain = sin(q.y * 85.0 + 5.0 * sin(q.x * 4.0 + q.z * 5.0));
        c *= 0.68 + 0.22 * grain + 0.10 * sin(q.y * 230.0);
        // 木箱的边框、接缝是颜色纹理，不改变几何法线。
        vec3 edge = extent[id] - abs(q);
        int edges = int(edge.x < 0.09) + int(edge.y < 0.09) + int(edge.z < 0.09);
        if (edges >= 2) c *= 0.35;
    }
    return c;
}

// 阴影射线穿过玻璃时衰减；这是直线透射近似，不模拟聚焦焦散。
vec3 visibility(vec3 o, vec3 d, float remaining) {
    if (!useShadows) return vec3(1);
    vec3 v = vec3(1);
    for (int step = 0; step < 16; ++step) {
        float t; vec3 n;
        int id = intersectScene(o, d, t, n);
        if (id < 0 || t >= remaining || id == LIGHT_ID) break;
        float transmission = useRefraction ? material[id].y : 0.0;
        if (transmission < 0.01) return vec3(0);
        v *= sqrt(transmission) * mix(vec3(1), baseColor[id], 0.16);
        o += d * (t + rayEpsilon * 2.0);
        remaining -= t + rayEpsilon * 2.0;
    }
    return v;
}

struct Ray { vec3 o; vec3 d; vec3 weight; int depth; int medium; };

vec3 trace(vec3 origin, vec3 direction) {
    // GLSL 不允许递归，用深度优先栈同时保留反射和折射支路。
    // 最大深度 6 时栈最多需要 7 项，完整二叉树最多处理 127 条射线。
    Ray stack[16];
    int count = 1;
    stack[0] = Ray(origin, direction, vec3(1), 0, -1);
    vec3 result = vec3(0);
    for (int iteration = 0; iteration < 128; ++iteration) {
        if (count == 0) break;
        Ray ray = stack[--count];
        float t; vec3 outward;
        int id = intersectScene(ray.o, ray.d, t, outward);
        if (id < 0) {
            result += ray.weight * mix(vec3(0.07,0.09,0.13), vec3(0.22,0.29,0.40),
                                       clamp(ray.d.y * 0.5 + 0.5, 0.0, 1.0));
            continue;
        }
        // Beer-Lambert 吸收；本实验的透明物体应保持互不嵌套、互不相交。
        if (ray.medium >= 0)
            ray.weight *= exp(-(vec3(1) - baseColor[ray.medium]) * t * 0.65);
        if (id == LIGHT_ID) { result += ray.weight * lightColor * lightPower; continue; }
        vec3 p = ray.o + ray.d * t;
        bool entering = dot(ray.d, outward) < 0.0;
        vec3 n = entering ? outward : -outward;
        vec3 color = surfaceColor(id, p);
        float mirror = useReflection ? material[id].x : 0.0;
        float transmission = useRefraction ? material[id].y : 0.0;
        float localWeight = (1.0 - mirror) * (1.0 - transmission);
        vec3 direct = vec3(0);
        int lightSamples = softShadows ? shadowSamples : 1;
        for (int sampleIndex = 0; sampleIndex < 16; ++sampleIndex) {
            if (sampleIndex >= lightSamples) break;
            vec3 lp = lightPosition;
            if (softShadows) {
                vec2 offset = vec2((float(sampleIndex)+0.5)/float(lightSamples),
                    fract(radicalInverse(sampleIndex)+0.5/float(lightSamples))) - 0.5;
                lp.xz += offset * lightSize;
            }
            vec3 toLight = lp - p;
            float lightDistance = length(toLight);
            vec3 l = toLight / lightDistance;
            float ndotl = max(dot(n,l), 0.0);
            if (ndotl > 0.0) {
                vec3 visible = visibility(p + n * rayEpsilon * 2.0, l, lightDistance);
                float illumination = lightPower / (1.0 + 0.10 * lightDistance * lightDistance);
                vec3 halfVector = normalize(l - ray.d);
                float specular = pow(max(dot(n,halfVector),0.0), material[id].w);
                direct += visible * lightColor * illumination *
                          (color * ndotl + vec3(specular * 0.22));
            }
        }
        direct /= float(lightSamples);
        result += ray.weight * localWeight * (color * ambientLight + direct);
        if (ray.depth >= maxDepth) continue;
        float reflectWeight = mirror;
        float refractWeight = 0.0;
        vec3 transmitted = vec3(0);
        int nextMedium = entering ? id : -1;
        if (transmission > 0.0) {
            float etaI = ray.medium < 0 ? 1.0 : material[ray.medium].z;
            float etaT = entering ? material[id].z : 1.0;
            float cosine = clamp(-dot(ray.d,n),0.0,1.0);
            float r0 = (etaI - etaT) / (etaI + etaT); r0 *= r0;
            float fresnel = r0 + (1.0-r0) * pow(1.0-cosine,5.0);
            transmitted = refract(ray.d,n,etaI/etaT);
            // 全反射时必须继续反射，即使关闭可选的普通镜面反射。
            if (dot(transmitted,transmitted) < 1e-8) fresnel = 1.0;
            reflectWeight += (1.0-mirror) * transmission * fresnel;
            refractWeight = (1.0-mirror) * transmission * (1.0-fresnel);
        }
        if (refractWeight > 0.001 && count < 16) {
            vec3 w = ray.weight * refractWeight;
            if (max(w.x,max(w.y,w.z)) > 0.002)
                stack[count++] = Ray(p - n*rayEpsilon*2.0, normalize(transmitted), w,
                                     ray.depth+1, nextMedium);
        }
        if (reflectWeight > 0.001 && count < 16) {
            vec3 w = ray.weight * reflectWeight;
            if (transmission < 0.01) w *= mix(vec3(1), color, 0.45);
            if (max(w.x,max(w.y,w.z)) > 0.002)
                stack[count++] = Ray(p + n*rayEpsilon*2.0, reflect(ray.d,n), w,
                                     ray.depth+1, ray.medium);
        }
    }
    return result;
}

void main() {
    vec2 screen = (gl_FragCoord.xy / resolution * 2.0 - 1.0);
    screen.x *= resolution.x / resolution.y;
    vec3 forward = normalize(target-eye);
    vec3 right = normalize(cross(forward,vec3(0,1,0)));
    vec3 up = cross(right,forward);
    vec3 d = normalize(forward + tan(radians(fieldOfView)*0.5) * (right*screen.x+up*screen.y));
    vec3 color = trace(eye,d);
    fragColor = vec4(color,1);
}
