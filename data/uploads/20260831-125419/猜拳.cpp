#include <bits/stdc++.h>
using namespace std;
int a[100001][4];
int n;
int a1,a2,a3;
int main()
{
	cin>>n;
	for(int i=1;i<=n;i++){
		for(int j=1;j<=3;j++){
			cin>>a[i][j];
		}
	}
	for(int i=1;i<=n;i++){
		if(!(a[i][1]!=a[i][2]&&a[i][2]!=a[i][3]&&a[i][3]!=a[i][1])){
			if(!(a[i][1]==a[i][2]==a[i][3])){
				if(a[i][1]==a[i][2]){
					if(a[i][2]<a[i][3]||a[i][2]==2&&a[i][3]==0){
						a2++;
					}else if(a[i][3]<a[i][1]||a[i][3]==2&&a[i][1]==0){
						a3++;
					}
				}else if(a[i][2]==a[i][3]){
					if(a[i][3]<a[i][1]||a[i][3]==2&&a[i][1]==0){
						a3++;
					}else if(a[i][1]<a[i][2]||a[i][1]==2&&a[i][2]==0){
						a1++;
					}
				}else if(a[i][3]==a[i][1]){
					if(a[i][1]<a[i][2]||a[i][1]==2&&a[i][2]==0){
						a1++;
					}else if(a[i][2]<a[i][3]||a[i][2]==2&&a[i][2]==0){
						a2++;
					}
				}
			}
		}
	}
	cout<<a1<<a2<<a3;
}
