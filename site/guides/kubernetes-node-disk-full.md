---
title: Kubernetes node disk full
description: Diagnose DiskPressure on a Kubernetes node, separate container images from pod logs and emptyDir data, and configure kubelet garbage collection and log rotation.
short: Find images, logs and temporary pod data behind DiskPressure.
---

A node can run out of space even when every application uses a persistent volume. Container images, writable layers, pod logs and disk-backed `emptyDir` volumes still use local storage. Check the filesystem that is full before choosing a cleanup.

## Find the filesystem and the workload

Run these on the affected Linux node:

```sh
df -h / /var/lib/kubelet /var/log/pods
df -i / /var/lib/kubelet /var/log/pods
sudo du -xhd1 /var/log/pods | sort -h | tail
sudo du -xhd1 /var/lib/kubelet/pods | sort -h | tail
sudo crictl images
sudo crictl ps -a
```

Missing directories can mean the distribution uses different paths. Configure `crictl` for the node's actual CRI endpoint; do not guess a runtime socket. Image sizes are not additive because images share layers, and the list alone does not tell you what is reclaimable. The [crictl reference](https://github.com/kubernetes-sigs/cri-tools/blob/master/docs/crictl.md) covers runtime configuration and inspection commands.

From a machine with cluster access, replace `NODE_NAME` with the node name:

```sh
kubectl describe node NODE_NAME
kubectl get pods -A --field-selector spec.nodeName=NODE_NAME -o wide
```

Compare the pod UIDs in `kubectl get pod -n NAMESPACE POD_NAME -o yaml` with directories under `/var/log/pods` and `/var/lib/kubelet/pods`. Do not recursively delete those directories: they can contain mounted volumes and live workload data.

## Let kubelet reclaim unused images

Kubelet already collects unused images. When usage passes `imageGCHighThresholdPercent`, it removes the oldest unused images until usage reaches `imageGCLowThresholdPercent`. Kubernetes recommends letting kubelet manage this rather than scheduling an external collector. See [image garbage collection](https://kubernetes.io/docs/concepts/architecture/garbage-collection/#container-image-lifecycle).

For a one-off recovery, an operator may choose the CRI tool's unused-image removal after checking running containers and the node's runtime:

```sh
sudo crictl rmi --prune
```

This changes runtime state. It removes images considered unused by the runtime, so later pod starts may need to download them again; registry access and credentials matter. It does not clean pod logs or persistent volumes. Prefer kubelet garbage collection for routine operation, and never remove containerd or CRI-O storage files by hand.

To start collection earlier, merge suitable thresholds into the existing kubelet configuration (an example, not a complete replacement):

```yaml
imageGCHighThresholdPercent: 80
imageGCLowThresholdPercent: 70
```

Keep the low threshold below the high threshold. Use your distribution or managed service's configuration mechanism and rollout procedure; the active file is not always `/var/lib/kubelet/config.yaml`. The [KubeletConfiguration reference](https://kubernetes.io/docs/reference/config-api/kubelet-config.v1beta1/) defines both fields.

## Bound container logs

If `/var/log/pods` dominates, identify the chatty workload and reduce its logging. Kubelet controls CRI container log rotation. For example, merge these fields into its existing configuration:

```yaml
containerLogMaxSize: 10Mi
containerLogMaxFiles: 5
```

These bound the size of an individual container's log files and the number retained, rather than the total for the node. Rotation is periodic, so a fast writer can temporarily exceed the size. `kubectl logs` exposes the latest log file; use a log collection service if older output must be retained. See [container log rotation](https://kubernetes.io/docs/concepts/cluster-administration/logging/#log-rotation) and the [configuration fields](https://kubernetes.io/docs/reference/config-api/kubelet-config.v1beta1/).

Avoid deleting or truncating live pod logs as a routine fix: you lose diagnostic history and bypass runtime log management.

## Check emptyDir and writable layers

Disk-backed `emptyDir` data survives container restarts but is lost when the pod is removed. Investigate the application before deleting or recreating its pod. An `emptyDir` with `medium: Memory` uses memory instead, so it is not a disk cleanup target.

For workloads that accumulate scratch files, set appropriate `ephemeral-storage` requests and limits and an `emptyDir.sizeLimit` in the workload specification. These help scheduling and eviction account for local usage; they do not reserve a separate disk. See [local ephemeral storage](https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/#local-ephemeral-storage).

## Understand DiskPressure before changing eviction thresholds

Kubelet monitors available bytes and inodes. `nodefs` describes the main node filesystem; a runtime may also expose separate `imagefs` or `containerfs` storage. Pruning images on a separate image filesystem will not free a full node filesystem used by logs.

When space is scarce, kubelet attempts reclamation and can evict pods. Lowering eviction thresholds to hide the condition leaves less recovery headroom. If you must customize `evictionHard`, check every resource threshold: partial overrides can stop other defaults from applying unless default merging is enabled. The [node-pressure eviction guide](https://kubernetes.io/docs/concepts/scheduling-eviction/node-pressure-eviction/) explains the signals, reclamation order and default-merging behavior.

After remediation, repeat `df -h`, `df -i` and `kubectl describe node NODE_NAME`. Check whether usage continues to grow; a larger disk only delays a workload that writes without bounds.
